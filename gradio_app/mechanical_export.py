"""Export confirmed setup or the current generated analysis as native Mechanical data."""
import hashlib
import json
from pathlib import Path


def setup_program(session, conditions):
    """Serialize the existing UI setup; never infer new engineering assumptions."""
    from fluent.contract import KINDS
    conditions = [r for r in conditions if r['type'] not in KINDS]
    from .thermal import KINDS as THERMAL_KINDS
    if any(r['type'] in THERMAL_KINDS for r in conditions):
        raise ValueError('Thermal conditions require an actual generated thermal analysis. Do not reconstruct them as a structural setup.')
    if conditions and (session.material is None or session.small_deformation is None):
        raise ValueError('Establish the material and analysis assumptions in chat before exporting these conditions.')
    code = "ctx.record('exportOnly', True)\n"
    if session.material is not None:
        code += f"""
for body in ctx.bodies:
    body.Material = {session.material!r}
analysis = Model.AddStaticStructuralAnalysis()
analysis.Name = 'Confirmed simulation setup'
analysis.IAnalysisSettings.LargeDeflection = {not session.small_deformation!r}
analysis.IAnalysisSettings.WeakSprings = WeakSpringsType.Off
Model.Mesh.ElementSize = Quantity({session.element_size_mm!r}, 'mm')
Model.Mesh.ElementOrder = ElementOrder.Quadratic
for number, condition in enumerate(ctx.conditions, 1):
    kind, values = condition['type'], condition['values']
    if kind == 'fixed':
        load = analysis.AddFixedSupport()
    elif kind in ('force', 'displacement'):
        load = analysis.AddForce() if kind == 'force' else analysis.AddDisplacement()
        load.DefineBy = LoadDefineBy.Components
        for axis in 'xyz':
            component = getattr(load, axis.upper() + 'Component')
            component.Output.DiscreteValues = [Quantity(values[axis], 'N' if kind == 'force' else 'mm')]
    elif kind == 'pressure':
        load = analysis.AddPressure()
        load.Magnitude.Output.DiscreteValues = [Quantity(values['magnitude'], 'MPa')]
    else:
        raise ValueError('Unsupported saved condition: ' + kind)
    load.Name = str(number) + ' ' + kind + ' ' + condition['faceKey']
    load.Location = ctx.selection([condition['faceKey']])
analysis.Solution.AddTotalDeformation()
analysis.Solution.AddEquivalentStress()
"""
    return {'title': 'Export confirmed Mechanical setup',
            'objective': 'Save the confirmed setup as .mechdat without meshing or solving.', 'code': code}


def native_path(service, result, kind='setup'):
    if not result or result.get('report', {}).get('status') != 'succeeded':
        return None
    value = result.get('mechanicalArchive' if kind == 'solved' else 'mechanicalFile')
    if kind == 'solved' and not result['report'].get('nativeArchive', {}).get('includesResults'):
        return None
    if not value:
        return None
    path = Path(value).resolve()
    if (path.suffix == ('.mechpz' if kind == 'solved' else '.mechdat') and path.is_relative_to((service.workspace.root / 'exports').resolve())
            and path.is_file() and path.stat().st_size):
        return path
    return None


def export_options(service, session):
    """The same availability rules drive disabled UI controls and the endpoint."""
    options = {'setup': {'enabled': False, 'reason': 'Confirm a simulation setup first.'},
               'solved': {'enabled': False, 'reason': 'Complete a successful simulation first.'}}
    if not session.model_id:
        return options
    project = service.workspace.get(session.model_id)
    from .thermal import KINDS as THERMAL_KINDS
    thermal_setup = ((project.get('simulationIntent') or {}).get('type') == 'heat_transfer'
                     or any(r['type'] in THERMAL_KINDS for r in project['boundaryConditions']))
    if native_path(service, session.result):
        options['setup'] = {'enabled': True, 'reason': 'Mechanical model and analysis setup.'}
    elif session.program_attempts or session.result:
        options['setup']['reason'] = 'Prepare the current analysis again to create its native export.'
    elif session.material is not None and session.small_deformation is not None and not thermal_setup:
        options['setup'] = {'enabled': True, 'reason': 'Confirmed setup; no solve required.'}
    if native_path(service, session.result, 'solved'):
        options['solved'] = {'enabled': True, 'reason': 'Mechanical project including solver results.'}
    return options


def export_mechanical(service, sid, model_id, revision, kind='setup'):
    with service.lock:
        session = service.existing(sid)
        if session.busy or session.running or session.turn_lock.locked():
            raise ValueError('Wait for the current operation before exporting the setup.')
        service._checked(sid, model_id, revision)
        if kind not in ('setup', 'solved'):
            raise ValueError('Choose a setup or solved simulation export.')
        option = export_options(service, session)[kind]
        if not option['enabled']:
            raise ValueError(option['reason'])
        # A successful generated job is authoritative: preserve its arbitrary
        # materials, analyses and mesh controls, rather than reconstructing it.
        path = native_path(service, session.result, kind)
        if path:
            return path
        if session.program_attempts or session.result:
            raise ValueError('The latest Mechanical project is not available for this setup. '
                             'Ask the assistant to prepare the current analysis again, then export.')
        project = service.workspace.get(model_id)
        conditions = project['boundaryConditions']
        fingerprint = hashlib.sha256(json.dumps({
            'model': model_id, 'conditions': conditions, 'material': session.material,
            'smallDeformation': session.small_deformation, 'elementSizeMm': session.element_size_mm,
        }, sort_keys=True).encode()).hexdigest()
        cached = session.mechanical_export
        if cached and cached['fingerprint'] == fingerprint:
            path = native_path(service, cached['result'])
            if path:
                return path
        program = setup_program(session, conditions)
        session.running = session.exporting = True
        session.revision += 1
    try:
        result = service.code_runner(service.workspace, model_id, program, selected_face=None)
        path = native_path(service, result)
        if not path:
            raise ValueError(result.get('report', {}).get('error') or
                             'Mechanical did not return a .mechdat file. Check the worker and try again.')
        with service.lock:
            session.mechanical_export = {'fingerprint': fingerprint, 'result': result}
        return path
    finally:
        with service.lock:
            session.running = session.exporting = False
            session.revision += 1
