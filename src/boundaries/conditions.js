export const conditionTypes = {
  fixed: { label: 'Fixed support', color: '#b69aff', unit: '', hint: 'Constrains translations: Ux = Uy = Uz = 0.' },
  displacement: { label: 'Prescribed displacement', color: '#68e0a7', unit: 'mm', hint: 'Global X/Y/Z displacements in mm. All three components are prescribed, including zeros.' },
  force: { label: 'Force', color: '#ff8d73', unit: 'N', hint: 'Total face force in global X/Y/Z, in newtons. Arrows show direction, not magnitude to scale.' },
  pressure: { label: 'Pressure', color: '#73bfff', unit: 'MPa', hint: 'Positive pressure acts inward along each local surface normal. Negative values act outward.' },
  velocity_inlet: { label: 'Velocity inlet', color: '#41d2b4', unit: 'm/s', hint: 'Global fluid velocity components in m/s.' },
  pressure_outlet: { label: 'Pressure outlet', color: '#ffb85a', unit: 'Pa gauge', hint: 'Outlet static pressure relative to the operating pressure, in Pa.' },
  wall: { label: 'No-slip wall', color: '#9ca3af', unit: '', hint: 'Stationary fluid wall; zero fluid velocity.' },
  symmetry: { label: 'Symmetry', color: '#69bef0', unit: '', hint: 'Zero normal velocity and zero normal gradients.' },
  temperature: { label: 'Temperature', color: '#ff6b6b', unit: '°C', hint: 'Prescribed surface temperature in degrees Celsius.' },
  heat_flux: { label: 'Heat flux', color: '#ff9947', unit: 'W/m²', hint: 'Positive heat flux enters the body; negative leaves it. Zero is allowed.' },
  convection: { label: 'Convection', color: '#49d3dd', unit: 'W/(m² K)', hint: 'Film coefficient and ambient temperature; graphics denote exchange, not a guessed heat-flow direction.' },
  radiation: { label: 'Radiation', color: '#f59edc', unit: '', hint: 'Emissivity and surroundings temperature; net heat-flow direction depends on surface temperature.' },
  adiabatic: { label: 'Insulation', color: '#e2d191', unit: '', hint: 'Adiabatic surface: zero normal heat flux.' },
};

const thermalFields = { temperature: ['temperature'], heat_flux: ['magnitude'], convection: ['coefficient', 'ambient_temperature'], radiation: ['emissivity', 'ambient_temperature'], adiabatic: [] };

export function validateConditions(records, modelId) {
  if (!Array.isArray(records)) throw new Error('Invalid boundary conditions list.');
  const ids = new Set();
  return records.map(record => {
    if (!record || typeof record.id !== 'string' || !record.id.trim() || ids.has(record.id) ||
        record.modelId !== modelId || typeof record.faceKey !== 'string' || !record.faceKey.trim() ||
        !Object.hasOwn(conditionTypes, record.type) ||
        typeof record.createdAt !== 'string' || !Number.isFinite(Date.parse(record.createdAt)) ||
        typeof record.updatedAt !== 'string' || !Number.isFinite(Date.parse(record.updatedAt))) {
      throw new Error('Invalid boundary condition identity, type, or timestamps.');
    }
    let values = {};
    if (Object.hasOwn(thermalFields, record.type)) {
      const fields = thermalFields[record.type];
      if (!record.values || Object.keys(record.values).length !== fields.length || !fields.every(k => Number.isFinite(record.values[k]))) throw new Error('Invalid heat-transfer boundary fields.');
      values = Object.fromEntries(fields.map(k => [k, record.values[k]]));
      for (const key of ['temperature', 'ambient_temperature']) {
        if (key in values && values[key] < -273.15) throw new Error('Temperature cannot be below absolute zero (°C).');
      }
      if (record.type === 'convection' && values.coefficient <= 0) throw new Error('Convection coefficient must be positive (W/(m² K)).');
      if (record.type === 'radiation' && (values.emissivity < 0 || values.emissivity > 1)) throw new Error('Emissivity must be between zero and one.');
    } else if (record.type === 'force' || record.type === 'displacement' || record.type === 'velocity_inlet') {
      if (!record.values || !['x', 'y', 'z'].every(axis => Number.isFinite(record.values[axis]))) {
        throw new Error('Boundary condition vector components must be finite numbers.');
      }
      values = Object.fromEntries(['x', 'y', 'z'].map(axis => [axis, record.values[axis]]));
      if (record.type === 'force' && !Object.values(values).some(value => value !== 0)) throw new Error('Force must have at least one nonzero component.');
      if (record.type === 'velocity_inlet' && !Object.values(values).some(value => value !== 0)) throw new Error('Inlet velocity must be nonzero.');
    } else if (record.type === 'pressure') {
      if (!Number.isFinite(record.values?.magnitude) || record.values.magnitude === 0) throw new Error('Pressure must be a finite, nonzero value.');
      values = { magnitude: record.values.magnitude };
    } else if (record.type === 'pressure_outlet') {
      if (!Number.isFinite(record.values?.gauge_pressure)) throw new Error('Outlet gauge pressure must be finite (Pa).');
      values = { gauge_pressure: record.values.gauge_pressure };
    } else if (['wall', 'symmetry'].includes(record.type)) {
      if (!record.values || Object.keys(record.values).length) throw new Error('Wall and symmetry conditions have no numeric values.');
    }
    ids.add(record.id);
    return { id: record.id, modelId, faceKey: record.faceKey, type: record.type, values, createdAt: record.createdAt, updatedAt: record.updatedAt };
  });
}

export function conditionSummary(condition) {
  const type = conditionTypes[condition.type];
  if (condition.type === 'fixed') return 'Ux = Uy = Uz = 0';
  if (condition.type === 'pressure') return `${condition.values.magnitude} MPa`;
  if (condition.type === 'pressure_outlet') return `${condition.values.gauge_pressure} Pa gauge`;
  if (condition.type === 'wall') return 'Stationary · no slip';
  if (condition.type === 'symmetry') return 'Zero normal flow';
  if (condition.type === 'temperature') return `${condition.values.temperature} °C`;
  if (condition.type === 'heat_flux') return `${condition.values.magnitude} W/m² · positive inward`;
  if (condition.type === 'convection') return `h ${condition.values.coefficient} W/(m² K) · ambient ${condition.values.ambient_temperature} °C`;
  if (condition.type === 'radiation') return `ε ${condition.values.emissivity} · surroundings ${condition.values.ambient_temperature} °C`;
  if (condition.type === 'adiabatic') return 'Adiabatic · zero normal heat flux';
  return `X ${condition.values.x}, Y ${condition.values.y}, Z ${condition.values.z} ${type.unit}`;
}
