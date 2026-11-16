"""Heat-transfer annotation units/validation, independent of a solver session."""
import math

KINDS = frozenset({'temperature', 'heat_flux', 'convection', 'radiation', 'adiabatic'})
FIELDS = {'temperature': {'temperature'}, 'heat_flux': {'magnitude'},
          'convection': {'coefficient', 'ambient_temperature'},
          'radiation': {'emissivity', 'ambient_temperature'}, 'adiabatic': set()}

RUNTIME_GUIDE = '''
THERMAL ANNOTATIONS AND ONBOARDING:
After CAD upload ask mechanical, heat transfer, or fluid dynamics. Record the user's answer with
set_simulation_intent. Fluid workflows ask about an existing or newly needed fluid domain; the user
may specify a box, cylindrical/pipe domain or custom standard method with set_fluid_domain.
set_fluid_domain records dimensions; create_fluid_domain constructs validated box/cylinder fluid CAD
as a derived model, subtracting solid obstacles when specified. Custom techniques need separate prep.
For thermal face annotations use temperature {temperature} °C; heat_flux {magnitude} W/m² positive
inward; convection {coefficient} W/(m² K), {ambient_temperature} °C; radiation {emissivity} 0..1,
{ambient_temperature} °C; adiabatic {}. Zero heat flux is allowed. Temperatures >= -273.15 °C.
Prescribed temperature and insulation are exclusive with other thermal conditions on the same face.
Structural/fluid/thermal annotation families are separate. Previews do not apply solver conditions.
Generated PyMechanical thermal code must explicitly apply saved annotations using verified face
selections and compatible units, and choose a valid thermal analysis/material/time model. The legacy
Structural Steel/static preset cannot implement thermal physics; Fluent remains isothermal here.
'''


def condition_values(kind, values):
    if kind not in FIELDS or not isinstance(values, dict) or set(values) != FIELDS[kind]:
        raise ValueError('Specify exactly the fields for the heat-transfer boundary condition.')
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values.values()):
        raise ValueError('Thermal boundary values must be finite numbers.')
    for key in ('temperature', 'ambient_temperature'):
        if key in values and values[key] < -273.15:
            raise ValueError('Temperature in degrees Celsius cannot be below absolute zero.')
    if kind == 'convection' and values['coefficient'] <= 0:
        raise ValueError('Convection coefficient must be positive, in W/(m² K).')
    if kind == 'radiation' and not 0 <= values['emissivity'] <= 1:
        raise ValueError('Emissivity must be between zero and one.')
    return dict(values)


def summary(kind, values):
    if kind == 'temperature':
        return f'Temperature {values["temperature"]} °C'
    if kind == 'heat_flux':
        return f'Heat flux {values["magnitude"]} W/m² (positive inward)'
    if kind == 'convection':
        return f'Convection h = {values["coefficient"]} W/(m² K), ambient {values["ambient_temperature"]} °C'
    if kind == 'radiation':
        return f'Radiation ε = {values["emissivity"]}, surroundings {values["ambient_temperature"]} °C'
    return 'Adiabatic / insulated (zero normal heat flux)'
