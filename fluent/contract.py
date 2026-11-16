"""Explicit SI CFD conditions and portable Fluent job validation."""
import ast
import hashlib
from pathlib import Path

from mechanical.contract import finite
from mechanical.program import validate_program as validate_python

KINDS = frozenset({'velocity_inlet', 'pressure_outlet', 'wall', 'symmetry'})
UNITS = {'length': 'mm', 'velocity': 'm/s', 'pressure': 'Pa',
         'density': 'kg/m^3', 'dynamicViscosity': 'Pa s'}


def verify_source_faces(current, stored):
    old = {f['key']: f for f in stored}
    if len(old) != len(stored) or set(old) != {f['key'] for f in current}:
        raise ValueError('The current CAD importer changed the stored face identities.')
    for face in current:
        prior = old[face['key']]
        if (abs(prior['areaMm2'] - face['areaMm2']) > max(1e-7, face['areaMm2'] * 1e-8)
                or len(prior.get('centroidMm', [])) != 3
                or any(abs(a-b) > 1e-7 for a,b in zip(prior['centroidMm'], face['centroidMm']))):
            raise ValueError('Stored face geometry differs from the exact submitted CAD. Reimport and reannotate.')


def condition_values(kind, values):
    fields = {'velocity_inlet': set('xyz'), 'pressure_outlet': {'gauge_pressure'},
              'wall': set(), 'symmetry': set()}
    if kind not in fields or not isinstance(values, dict) or set(values) != fields[kind]:
        raise ValueError('Supply exactly the fields for this Fluent condition; walls are stationary no-slip, pressure outlets use gauge_pressure in Pa.')
    if not all(finite(v) for v in values.values()):
        raise ValueError('Fluent condition values must be finite SI numbers.')
    if kind == 'velocity_inlet' and not any(values.values()):
        raise ValueError('A velocity inlet requires a nonzero global velocity vector (m/s).')
    return dict(values)


def validate_analysis(value):
    required = {'domain', 'regime', 'density', 'dynamic_viscosity', 'operating_pressure',
                'mesh_size_mm', 'max_iterations', 'residual_tolerance', 'mass_imbalance_tolerance'}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError('Establish all Fluent analysis assumptions before running.')
    if value['domain'] != 'fluid-volume' or value['regime'] != 'steady-laminar-incompressible':
        raise ValueError('The optional saved Fluent analysis card records steady laminar incompressible isothermal assumptions. Other agent-authored steady setups do not require this card; prepare an actual fluid-volume CAD and confirm assumptions in the code proposal.')
    for key in required - {'domain', 'regime', 'max_iterations'}:
        if not finite(value[key]) or value[key] <= 0:
            raise ValueError(key + ' must be positive and finite.')
    if type(value['max_iterations']) is not int or not 1 <= value['max_iterations'] <= 2000:
        raise ValueError('Use 1–2000 iterations.')
    if value['residual_tolerance'] >= 1 or value['mass_imbalance_tolerance'] >= 1:
        raise ValueError('Convergence tolerances must be fractions between zero and one.')
    return dict(value)


def validate_program(program):
    digest = validate_python(program)
    tree = ast.parse(program['code'])
    blocked = {'mesh', 'configure', 'iterate', 'calculate', 'dual_time_iterate', 'execute_tui', 'scheme_eval',
               'eval', 'exec', 'launch_fluent', 'from_install', 'read_case', 'read_case_data',
               'read_mesh', 'write_case', 'write_case_data', 'write_data', 'exit',
               'system', 'load', 'read', 'write', 'start_journal', 'scale', 'translate',
               'rotate', 'adapt', 'switch_to_meshing', 'switch_to_solver'}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {'tui', 'scheme', 'scheme_eval'}:
            raise ValueError('Use public PyFluent settings and ctx helpers, not TUI/Scheme or nested commands.')
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in blocked:
            raise ValueError('The fixed ctx.mesh/ctx.configure workflow is removed. Author PyFluent setup and use ctx.generate_mesh, ctx.solve and ctx.save_case for checked operations.')
    return digest


def validate_request(request):
    if request.get('schemaVersion') != 3 or request.get('solver') != 'fluent' or request.get('faceMapping') != 'python-ocp-v1':
        raise ValueError('Unsupported Fluent job or face namespace.')
    if hashlib.sha256(Path(request['stepFile']).read_bytes()).hexdigest() != request.get('modelId'):
        raise ValueError('STEP SHA-256 mismatch.')
    validate_program(request.get('program'))
    if request.get('executionMode') != 'agent-authored-v2':
        raise ValueError('The old fixed Fluent workflow is removed; submit agent-authored-v2 code.')
    if request.get('analysis') is not None:
        validate_analysis(request['analysis'])
    if request.get('units') != UNITS:
        raise ValueError('Fluent requests must declare mm geometry and SI flow units.')
    if request.get('settings') != {'fluentVersion': 261, 'solverCores': 1, 'maxCells': 32000}:
        raise ValueError('Expected Fluent 261, one core and a 32000-cell cap.')
    faces = request.get('sourceFaces')
    if not isinstance(faces, list) or not faces or len({f['key'] for f in faces}) != len(faces):
        raise ValueError('Unique source CAD faces are required.')
    keys = {f['key'] for f in faces}
    for face in faces:
        if (not finite(face.get('areaMm2')) or face['areaMm2'] <= 0
                or len(face.get('centroidMm', [])) != 3 or not all(map(finite, face['centroidMm']))):
            raise ValueError('Source face descriptors must contain finite area and centroid geometry.')
    if request.get('selectedFace') is not None and request['selectedFace'] not in keys:
        raise ValueError('The selected face is not in this CAD.')
    records = request.get('boundaryConditions')
    if not isinstance(records, list):
        raise ValueError('Fluent boundary conditions are required.')
    seen, ids = set(), set()
    for row in records:
        if (row.get('faceKey') not in keys or row['faceKey'] in seen or row.get('id') in ids
                or not row.get('id') or row.get('modelId') != request['modelId']):
            raise ValueError('Fluent conditions need unique IDs, one condition per mapped face, and matching CAD identity.')
        seen.add(row['faceKey']); ids.add(row['id'])
        condition_values(row.get('type'), row.get('values'))
    return records
