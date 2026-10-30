export const conditionTypes = {
  fixed: { label: 'Fixed support', color: '#b69aff', unit: '', hint: 'Constrains translations: Ux = Uy = Uz = 0.' },
  displacement: { label: 'Prescribed displacement', color: '#68e0a7', unit: 'mm', hint: 'Global X/Y/Z displacements in mm. All three components are prescribed, including zeros.' },
  force: { label: 'Force', color: '#ff8d73', unit: 'N', hint: 'Total face force in global X/Y/Z, in newtons. Arrows show direction, not magnitude to scale.' },
  pressure: { label: 'Pressure', color: '#73bfff', unit: 'MPa', hint: 'Positive pressure acts inward along each local surface normal. Negative values act outward.' },
};

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
    if (record.type === 'force' || record.type === 'displacement') {
      if (!record.values || !['x', 'y', 'z'].every(axis => Number.isFinite(record.values[axis]))) {
        throw new Error('Boundary condition vector components must be finite numbers.');
      }
      values = Object.fromEntries(['x', 'y', 'z'].map(axis => [axis, record.values[axis]]));
      if (record.type === 'force' && !Object.values(values).some(value => value !== 0)) throw new Error('Force must have at least one nonzero component.');
    } else if (record.type === 'pressure') {
      if (!Number.isFinite(record.values?.magnitude) || record.values.magnitude === 0) throw new Error('Pressure must be a finite, nonzero value.');
      values = { magnitude: record.values.magnitude };
    }
    ids.add(record.id);
    return { id: record.id, modelId, faceKey: record.faceKey, type: record.type, values, createdAt: record.createdAt, updatedAt: record.updatedAt };
  });
}

export function conditionSummary(condition) {
  const type = conditionTypes[condition.type];
  if (condition.type === 'fixed') return 'Ux = Uy = Uz = 0';
  if (condition.type === 'pressure') return `${condition.values.magnitude} MPa`;
  return `X ${condition.values.x}, Y ${condition.values.y}, Z ${condition.values.z} ${type.unit}`;
}
