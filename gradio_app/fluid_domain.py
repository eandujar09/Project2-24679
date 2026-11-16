"""User-defined CFD dimensions; construction is a separate confirmed operation."""
import math


def validate_domain(kind, cad_role, parameters, description):
    if kind not in ('existing', 'box', 'cylinder', 'custom'):
        raise ValueError('Choose an existing fluid volume, box, cylinder/pipe, or custom domain technique.')
    if cad_role not in ('fluid_volume', 'obstacle', 'reference'):
        raise ValueError('Establish whether the uploaded CAD is fluid volume, an obstacle to subtract, or reference geometry.')
    if not isinstance(parameters, dict) or any(type(v) not in (int,float) or not math.isfinite(v) for v in parameters.values()):
        raise ValueError('Domain dimensions/coordinates must be finite numbers in mm; axis components are dimensionless.')
    if not isinstance(description, str) or not description.strip() or len(description) > 4000:
        raise ValueError('Describe the domain, geometry role and chosen preparation technique.')
    fields = {'existing': set(),
              'box': {'min_x','min_y','min_z','max_x','max_y','max_z'},
              'cylinder': {'origin_x','origin_y','origin_z','axis_x','axis_y','axis_z','radius','length'}}
    if kind in fields and set(parameters) != fields[kind]:
        raise ValueError('Supply exactly the required dimensions: ' + ', '.join(sorted(fields[kind])))
    if kind == 'existing' and cad_role != 'fluid_volume':
        raise ValueError('An existing domain must represent the actual fluid volume, not just a bounding solid or obstacle.')
    if kind == 'box' and any(parameters['max_'+a] <= parameters['min_'+a] for a in 'xyz'):
        raise ValueError('Each box maximum must exceed its minimum (mm).')
    if kind == 'cylinder':
        if parameters['radius'] <= 0 or parameters['length'] <= 0:
            raise ValueError('Cylinder inner fluid radius and length must be positive (mm).')
        axis_length = math.hypot(*(parameters['axis_'+a] for a in 'xyz'))
        if not math.isfinite(axis_length) or axis_length == 0:
            raise ValueError('Cylinder axis must be a nonzero direction.')
    return {'kind':kind, 'cadRole':cad_role, 'parameters':dict(parameters), 'description':description.strip(),
            'status':'ready' if kind == 'existing' else 'needs_preparation'}


DOMAIN_QUESTION = ('Does the uploaded CAD already contain the fluid domain, or should a domain be added? '
                   'You can define a box enclosure, cylindrical/pipe domain, or another standard technique. '
                   'Please also tell me whether the CAD represents the fluid volume or a solid obstacle.')


def domain_summary(domain):
    p = domain['parameters']
    if domain['kind'] == 'box':
        return 'Box: '+', '.join(f'{a.upper()} {p["min_"+a]:g} to {p["max_"+a]:g}' for a in 'xyz')+' mm.'
    if domain['kind'] == 'cylinder':
        return ('Cylinder: origin '+str([p['origin_'+a] for a in 'xyz'])+' mm; axis '+str([p['axis_'+a] for a in 'xyz'])+
                f'; radius {p["radius"]:g} mm; length {p["length"]:g} mm.')
    return domain['kind'].capitalize()+' fluid domain.'
