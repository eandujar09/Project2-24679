"""Fresh, time-limited PyFluent generated-code process, launched by the shared worker."""
import argparse
import contextlib
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
import traceback

from mechanical.contract import write_json
from .contract import validate_request, verify_source_faces


def license_failure_diagnostic(text):
    """A license banner or successful checkout is not evidence of a license failure."""
    patterns = (
        r'unexpected licen[sc]e problem',
        r'licen[sc](?:e|ing) (?:manager )?error',
        r'licen[sc]e (?:check[ -]?out|acquisition) (?:has )?failed',
        r'licen[sc]e (?:is |has )?(?:not available|unavailable|expired|denied)',
        r'no valid licen[sc]e',
        r'(?:unable|failed|cannot|could not) to (?:obtain|acquire|check[ -]?out) (?:a |the )?licen[sc]e',
    )
    for line in text.splitlines():
        if any(re.search(pattern,line,re.IGNORECASE) for pattern in patterns):
            return line.strip()
    return None


def import_surface_mesh(workflow, path):
    """The generated STL is a mesh file, not a CAD-file import."""
    workflow.InitializeWorkflow(WorkflowType='Watertight Geometry')
    tasks = workflow.TaskObject
    task = tasks['Import Geometry']
    task.Arguments = {'FileFormat':'Mesh','MeshFileName':str(path),'MeshUnit':'mm','LengthUnit':'mm'}
    task.Execute()
    return tasks


def select_fluid_region(regions, cad_volume_mm3, relative_tolerance=0.01):
    """Match CAD volume, never the largest region or a face-derived name.

    Subsequent trimmed-face matching remains mandatory: volume agreement alone
    is not proof of geometric correspondence.
    """
    if not math.isfinite(cad_volume_mm3) or cad_volume_mm3 <= 0 or not regions:
        raise ValueError('Cannot identify a fluid region without positive CAD and region volumes.')
    if any(not math.isfinite(r['volumeMm3']) or r['volumeMm3'] <= 0 for r in regions):
        raise ValueError('Fluent returned invalid enclosed-region volumes.')
    matches = [r for r in regions if abs(r['volumeMm3']-cad_volume_mm3) <= relative_tolerance*cad_volume_mm3]
    if len(matches) != 1:
        raise ValueError('Fluent regions do not uniquely match the confirmed fluid CAD volume; stopping before volume meshing.')
    return matches[0]


def update_fluid_regions(meshing, tasks, cad_volume_mm3):
    utilities = meshing.meshing_utilities
    objects = list(utilities.get_objects(type_name='mesh'))
    if len(objects) != 1:
        raise ValueError('Expected one surface-mesh object before fluid-region selection.')
    obj = objects[0]
    names = list(utilities.get_regions(object_name=obj))
    regions = []
    for name in names:
        values = list(utilities.get_region_volume(object_name=obj,region_name=name))
        if len(values) != 1:
            raise ValueError('Fluent did not return one volume for an enclosed region.')
        regions.append({'name':name,'volumeMm3':float(values[0])})
    fluid = select_fluid_region(regions,cad_volume_mm3)
    # Describe Geometry initialized all enclosed regions as fluid. Update both
    # old and new lists: without old lists Fluent silently keeps those defaults.
    types = ['fluid' if r is fluid else 'dead' for r in regions]
    tasks['Update Regions'].Arguments = {
        'RegionNameList':names,'RegionTypeList':types,
        'OldRegionNameList':names,'OldRegionTypeList':['fluid']*len(names)}
    tasks['Update Regions'].Execute()
    return {'cadVolumeMm3':cad_volume_mm3,'volumeToleranceRelative':0.01,
            'regions':[dict(r,type=t) for r,t in zip(regions,types)],
            'selectionMethod':'Unique CAD-volume match; trimmed-face verification required after meshing.'}


class ExecutionContext:
    def __init__(self, request, directory, report, launcher=None):
        self.request, self.directory, self.report = request, Path(directory), report
        self.analysis = dict(request.get('analysis') or {})
        self.conditions = request['boundaryConditions']
        self.selected_face = request.get('selectedFace')
        self.solver = None
        self.meshing = None
        self._launcher = launcher
        self.tasks = None
        self.geometry = None
        self._total_iterations = 0
        self._mapping = {}
        self._zones = {}
        self._iterated = False

    def artifact(self, name):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', name) or '..' in name:
            raise ValueError('Use a simple job-local artifact filename.')
        return str(self.directory / name)

    def describe(self, obj):
        result = {'type':str(type(obj)),'members':[n for n in dir(obj) if not n.startswith('_')][:250]}
        if getattr(obj,'__doc__',None):
            result['doc'] = str(obj.__doc__)[:4000]
        return result

    def record(self, name, value, unit=None):
        json.dumps(value, allow_nan=False)
        self.report['metrics'][name] = {'value': value, 'unit': unit}
        return value

    def table(self, name, rows):
        json.dumps(rows, allow_nan=False)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError('Tables must be lists of dictionaries.')
        write_json(self.artifact(name + '.json'), rows)
        self.report['tables'][name] = rows
        if rows:
            with Path(self.artifact(name + '.csv')).open('w', newline='', encoding='utf-8') as stream:
                fields = list(dict.fromkeys(k for row in rows for k in row))
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader(); writer.writerows(rows)
        return rows

    def mesh_counts(self):
        names = self.solver.settings.setup.cell_zone_conditions.fluid.get_object_names()
        if len(names) != 1 or self.solver.settings.setup.cell_zone_conditions.solid.get_object_names():
            raise ValueError('The supported CFD scope requires exactly one fluid cell zone and no solid cell zones.')
        info = self.solver.fields.solution_variable_info.get_zones_info()
        cells = sum(info[name].count for name in names)
        if type(cells) is not int or not 0 < cells <= self.request['settings']['maxCells']:
            raise ValueError('Fluent mesh exceeds the 32000-cell worker limit or is empty.')
        self.report['mesh'] = {'cells': cells}
        return self.report['mesh']

    def prepare(self):
        if self.solver or self.meshing:
            raise ValueError('This job already has a fresh imported Fluent session.')
        from gradio_app.geometry import read_step, mechanical_signatures, read_shape
        from OCP.GProp import GProp_GProps
        from OCP.BRepGProp import BRepGProp

        source = Path(self.request['stepFile'])
        meshes, faces = read_step(source)
        signatures = mechanical_signatures(source, require_single_solid=True)
        verify_source_faces(signatures, self.request['sourceFaces'])
        shape = read_shape(source)
        volume_properties = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape,volume_properties)
        cad_volume_mm3 = abs(volume_properties.Mass())
        # Separate STL solids preserve original B-rep face partitions without trusting labels later.
        stl = Path(self.artifact('boundaries.stl'))
        with stl.open('w', encoding='ascii') as stream:
            for face, mesh in zip(faces, meshes):
                label = 'cad_face_' + str(face['index'])
                stream.write('solid ' + label + '\n')
                for normal, triangle in zip(mesh.face_normals, mesh.triangles):
                    stream.write('facet normal ' + ' '.join(map(str, normal)) + '\nouter loop\n')
                    for vertex in triangle:
                        stream.write('vertex ' + ' '.join(map(str, vertex)) + '\n')
                    stream.write('endloop\nendfacet\n')
                stream.write('endsolid ' + label + '\n')
        launch = self._launcher
        if launch is None:
            import ansys.fluent.core as pyfluent
            launch = pyfluent.launch_fluent
        self.report['errorStage'] = 'fluent-launch'
        try:
            self.meshing = launch(product_version='26.1.0', mode='meshing', dimension=3,
                                  precision='double', processor_count=1, ui_mode='no_gui',
                                  cwd=str(self.directory), start_timeout=120)
        except Exception as exc:
            transcripts = sorted(self.directory.glob('fluent-*.trn'))
            diagnostics = '\n'.join(p.read_text(errors='replace')[-12000:] for p in transcripts[-2:])
            failure = license_failure_diagnostic(diagnostics)
            if failure:
                raise ValueError('This Fluent launch reported a new license failure: '+failure+'. See the retained transcript. '+str(exc)) from exc
            raise
        self.report['errorStage'] = 'meshing-and-face-mapping'
        self.tasks = import_surface_mesh(self.meshing.workflow,stl)
        self.geometry = {'faces':signatures,'cadVolumeMm3':cad_volume_mm3,
                         'surfaceFile':str(stl),'lengthUnit':'mm','mappingStatus':'not_meshed'}
        self.report['geometry'] = dict(self.geometry)
        return self.geometry

    def update_regions(self):
        """CAD-domain integrity helper; no physics, sizing or volume fill defaults."""
        if self.tasks is None or self.solver:
            raise ValueError('Use the imported meshing session before generating a volume mesh.')
        evidence = update_fluid_regions(self.meshing,self.tasks,self.geometry['cadVolumeMm3'])
        self.report['meshPreparation'] = evidence
        write_json(self.artifact('mesh-preparation.json'),evidence)
        return evidence

    def generate_mesh(self, tolerance_mm=0.08):
        """Execute the agent-configured volume task and verify original CAD faces."""
        if self.tasks is None or self.solver:
            raise ValueError('Configure the fresh imported meshing session first.')
        if not isinstance(tolerance_mm,(int,float)) or isinstance(tolerance_mm,bool) or not 0 < tolerance_mm <= 0.1:
            raise ValueError('CAD mapping tolerance must be positive and at most 0.1 mm.')
        arguments = self.tasks['Generate the Volume Mesh'].Arguments.get_state()
        if not arguments.get('VolumeFill'):
            raise ValueError('Author explicit volume-mesh controls before ctx.generate_mesh; no worker fill template is supplied.')
        from gradio_app.geometry import read_shape
        from .mapping import triangulate, match_zones
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
        from OCP.TopAbs import TopAbs_FACE
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS
        from OCP.gp import gp_Pnt
        import numpy as np
        from ansys.fluent.core import SurfaceFieldDataRequest, SurfaceDataType
        self.report['errorStage'] = 'meshing-and-face-mapping'
        self.report.setdefault('meshPreparation',{}).update(
            volumeControls=arguments,
            surfaceControls=self.tasks['Generate the Surface Mesh'].Arguments.get_state(),
            maxCells=self.request['settings']['maxCells'])
        write_json(self.artifact('mesh-preparation.json'),self.report['meshPreparation'])
        self.tasks['Generate the Volume Mesh'].Execute()
        self.solver = self.meshing.switch_to_solver()
        self.mesh_counts()
        self.solver.settings.mesh.check()
        # Geometry queries are in SI meters after Fluent's mm import conversion.
        names = self.solver.fields.field_data.surfaces.allowed_values()
        boundaries = self.solver.settings.setup.boundary_conditions
        bc_names = {n for kind in ('wall', 'velocity_inlet', 'pressure_outlet', 'symmetry')
                    for n in getattr(boundaries, kind).get_object_names()}
        names = [n for n in names if n in bc_names]
        if not names:
            raise ValueError('Fluent returned no boundary surfaces; cannot verify CAD scoping.')
        data = self.solver.fields.field_data.get_field_data(SurfaceFieldDataRequest(
            surfaces=names, data_types=[SurfaceDataType.Vertices, SurfaceDataType.FacesConnectivity],
            flatten_connectivity=True))
        zones = {n: triangulate(np.asarray(data[n].vertices) * 1000, data[n].connectivity) for n in names}
        original = {}
        source = Path(self.request['stepFile'])
        shape = read_shape(source)
        explorer = TopExp_Explorer(shape, TopAbs_FACE)
        for face in self.geometry['faces']:
            if not explorer.More():
                raise ValueError('Original CAD faces are missing.')
            original[face['key']] = TopoDS.Face_s(explorer.Current()); explorer.Next()

        def exact_distance(key, points):
            maximum = 0.0
            for p in points:
                vertex = BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, p))).Vertex()
                query = BRepExtrema_DistShapeShape(vertex, original[key])
                query.Perform()
                if not query.IsDone():
                    raise ValueError('Exact trimmed-face distance query failed.')
                maximum = max(maximum, query.Value())
            return maximum

        self._mapping, evidence = match_zones(self.geometry['faces'], zones, exact_distance, tolerance_mm)
        self._zones = zones
        self.geometry.update(mappingStatus='verified',faceZones=dict(self._mapping))
        self.report['geometry'] = {**self.geometry,'mappingEvidence': evidence,
            'mappingMethod': 'Trimmed CAD distance, reverse samples and 2% area agreement; finite sampled correspondence, not topology proof.'}
        write_json(self.artifact('face-mapping.json'), self.report['geometry'])
        return self.solver

    def selection(self, keys):
        if not keys or any(key not in self._mapping for key in keys):
            raise ValueError('A requested CAD face lacks verified Fluent mapping; never guess zone IDs.')
        return [self._mapping[key] for key in keys]

    def solve(self, max_iterations=None, residual_tolerance=None, mass_imbalance_tolerance=None,
              mass_flow_zones=None):
        if not self.solver or not self._mapping:
            raise ValueError('Use ctx.generate_mesh and author the solver setup before solving.')
        self.mesh_counts()
        max_iterations = self.analysis.get('max_iterations') if max_iterations is None else max_iterations
        residual_tolerance = self.analysis.get('residual_tolerance') if residual_tolerance is None else residual_tolerance
        mass_imbalance_tolerance = self.analysis.get('mass_imbalance_tolerance') if mass_imbalance_tolerance is None else mass_imbalance_tolerance
        for name,value in [('max_iterations',max_iterations),('residual_tolerance',residual_tolerance),
                           ('mass_imbalance_tolerance',mass_imbalance_tolerance)]:
            if name in self.analysis and value != self.analysis[name]:
                raise ValueError('The authored solve differs from saved '+name+'; confirm and update that assumption first.')
        if type(max_iterations) is not int or not 1 <= max_iterations <= 2000 or self._total_iterations+max_iterations > 2000:
            raise ValueError('Supply a positive iteration budget; at most 2000 requested iterations per job.')
        for value in (residual_tolerance,mass_imbalance_tolerance):
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0 < value < 1:
                raise ValueError('Supply explicit residual and mass-imbalance tolerances between zero and one.')
        if mass_flow_zones is None:
            mass_flow_zones = self.selection([r['faceKey'] for r in self.conditions if r['type'] in ('velocity_inlet','pressure_outlet')])
        if (not isinstance(mass_flow_zones,list) or len(mass_flow_zones)<2 or any(not isinstance(n,str) for n in mass_flow_zones)
                or len(set(mass_flow_zones))!=len(mass_flow_zones)
                or any(n not in self._mapping.values() for n in mass_flow_zones)):
            raise ValueError('Supply distinct verified mass-flow boundary zones covering every open boundary.')
        self.report['errorStage'] = 'fluent-setup-verification'
        self._assert_setup()
        self.report['errorStage'] = 'fluent-iteration-and-convergence'
        setup = self.solver.settings.setup
        if setup.general.solver.time() != 'steady':
            raise ValueError('The resource-checked Fluent solve helper currently supports steady iteration, not transient stepping.')
        self.report['actualSetup'] = {key:getattr(setup,name).get_state() for key,name in
            [('models','models'),('general','general'),('cellZones','cell_zone_conditions'),
             ('materials','materials'),('boundaries','boundary_conditions')]}
        write_json(self.artifact('actual-setup.json'),self.report['actualSetup'])
        open_kinds = {'velocity_inlet','pressure_inlet','pressure_outlet','mass_flow_inlet','outflow',
                      'inlet_vent','outlet_vent','intake_fan','exhaust_fan'}
        boundary_state = self.report['actualSetup']['boundaries']
        open_names = {name for kind,values in boundary_state.items()
                      if kind in open_kinds and isinstance(values,dict) for name in values}
        if open_names != set(mass_flow_zones):
            raise ValueError('Mass-balance zones must match every actual open boundary; cannot omit or invent a flux surface.')
        solution = self.solver.settings.solution
        write_json(self.artifact('numerical-settings.json'), {
            'methods': solution.methods.get_state(), 'controls': solution.controls.get_state(),
            'maximumIterations': max_iterations,'residualTolerance':residual_tolerance,
            'massImbalanceTolerance':mass_imbalance_tolerance,'massFlowZones':mass_flow_zones})
        equations = solution.monitor.residual.equations
        required = {n for n in equations.get_object_names() if equations[n].is_active()}
        if not required:
            raise ValueError('No active residual equations are available to verify convergence.')
        for name in required:
            equations[name].monitor = True
            equations[name].check_convergence = True
            equations[name].absolute_criteria = residual_tolerance
        # Initialization method is agent-authored, not a hidden hybrid template.
        self.solver.monitors.refresh(self.solver, None)
        before = self.solver.monitors.get_monitor_set_data(monitor_set_name='residual') if self._iterated else ([],{})
        self._iterated = True
        self._total_iterations += max_iterations
        solution.run_calculation.iterate(iter_count=max_iterations)
        history = self.solver.monitors.get_monitor_set_data(monitor_set_name='residual')
        iterations, series = history
        if not len(iterations) or not required.issubset(series):
            raise ValueError('Actual Fluent residual history is unavailable; convergence cannot be verified.')
        if len(before[0]) and iterations[-1] <= before[0][-1]:
            raise ValueError('Fluent returned stale residual history; no new solve can be verified.')
        rows = [{'iteration': int(step), **{n: float(v[i]) for n, v in series.items()}} for i, step in enumerate(iterations)]
        self.table('residuals', rows)
        self.report['tables']['residuals'] = rows[-20:]
        self.record('residualHistoryRows', len(rows))
        last = rows[-1]
        residual_ok = all(math.isfinite(last[n]) and 0 <= last[n] <= residual_tolerance for n in required)
        fluxes = []
        for name in mass_flow_zones:
            value = float(self.solver.fields.reduction.mass_flow_integral(expression='1', locations=[name], ctxt=self.solver))
            if not math.isfinite(value):
                raise ValueError('Fluent returned nonfinite mass flow.')
            fluxes.append({'zone':name,'massFlowKgS':value})
        total = sum(abs(row['massFlowKgS']) for row in fluxes) / 2
        imbalance = abs(sum(row['massFlowKgS'] for row in fluxes)) / total if total else None
        mass_ok = imbalance is not None and imbalance <= mass_imbalance_tolerance
        self.table('mass_balance', fluxes)
        self.record('relativeMassImbalance', imbalance)
        converged = residual_ok and mass_ok
        self.report['converged'] = converged
        self.report['verifiedSolves'].append({'solver': 'fluent', 'status': 'Done' if converged else 'NotConverged',
            'iterations': int(iterations[-1]), 'residualsSatisfied': residual_ok, 'massBalanceSatisfied': mass_ok,
            'relativeMassImbalance': imbalance, 'cells': self.report['mesh']['cells']})
        self.save_case()
        if not converged:
            raise ValueError('Fluent iterations completed but the agreed residual AND mass-balance criteria were not met. Native case/data and measured diagnostics are retained.')
        return self.report['verifiedSolves'][-1]

    def _assert_setup(self):
        """Read back saved assumptions/conditions; never create physics or loads."""
        setup = self.solver.settings.setup
        checks = []
        # Existing saved laminar assumptions remain binding user data, not defaults
        # imposed on jobs that have no such saved analysis.
        if self.analysis:
            checks += [(setup.general.solver.time(),'steady'),(setup.models.viscous.model(),'laminar'),
                       (setup.models.energy.enabled(),False),
                       (setup.general.operating_conditions.operating_pressure(),self.analysis['operating_pressure'])]
            for name in setup.cell_zone_conditions.fluid.get_object_names():
                material_name = setup.cell_zone_conditions.fluid[name].general.material()
                material = setup.materials.fluid[material_name]
                # Fluent 261 scalar material properties canonicalize a constant
                # numeric input as option='value'. Expression/UDF options must
                # still fail even if their cached numeric value happens to match.
                checks += [(material.density.option() in ('constant','value'),True),
                           (material.density.value(),self.analysis['density']),
                           (material.viscosity.option() in ('constant','value'),True),
                           (material.viscosity.value(),self.analysis['dynamic_viscosity'])]
        for row in self.conditions:
            name = self._mapping[row['faceKey']]
            collection = getattr(setup.boundary_conditions, row['type'])
            if name not in collection.get_object_names():
                raise ValueError('Agent-authored code did not implement a confirmed Fluent boundary type.')
            momentum = collection[name].momentum if row['type'] != 'symmetry' else None
            if row['type'] == 'velocity_inlet':
                checks += [(momentum.velocity_specification_method(), 'Components'), (momentum.reference_frame(), 'Absolute')]
                checks += [(momentum.velocity_components[i].value(), row['values'][a]) for i, a in enumerate('xyz')]
            elif row['type'] == 'pressure_outlet':
                checks.append((momentum.gauge_pressure.value(), row['values']['gauge_pressure']))
            elif row['type'] == 'wall':
                checks += [(momentum.wall_motion(), 'Stationary Wall'), (momentum.shear_condition(), 'No Slip')]
        if any(actual != expected for actual, expected in checks):
            raise ValueError('The Fluent physics or boundaries differ from the confirmed setup. Propose the changed assumptions first.')

    def save_case(self):
        if not self.solver:
            raise ValueError('Generate a checked solver mesh before exporting a case.')
        if self._iterated:
            self.solver.settings.file.write_case_data(file_name=self.artifact('case.cas.h5'))
        else:
            self.solver.settings.file.write_case(file_name=self.artifact('case.cas.h5'))

    def capture(self, field, name):
        if field not in ('pressure', 'velocity-magnitude') or not self._iterated:
            raise ValueError('Capture pressure or velocity-magnitude after actual iterations.')
        import numpy as np
        self.report['errorStage'] = 'fluent-postprocessing'
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from ansys.fluent.core import ScalarFieldDataRequest
        names = list(self._zones)
        result = self.solver.fields.field_data.get_field_data(ScalarFieldDataRequest(
            surfaces=names, field_name=field, node_value=True, boundary_value=True))
        rows = []
        for zone in names:
            values = np.asarray(result[zone]).ravel()
            points = np.asarray(self._zones[zone].vertices) / 1000
            if len(values) != len(points) or not np.isfinite(values).all():
                raise ValueError('Scalar surface field does not match the verified mesh vertices.')
            rows.extend({'zone': zone, 'x_m': float(p[0]), 'y_m': float(p[1]), 'z_m': float(p[2]), field: float(v)} for p, v in zip(points, values))
        # Large field arrays belong in artifacts, not in every subsequent model prompt.
        with Path(self.artifact(name + '.csv')).open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=['zone', 'x_m', 'y_m', 'z_m', field])
            writer.writeheader(); writer.writerows(rows)
        self.report['results'][field] = {'minimum': min(r[field] for r in rows),
                                          'maximum': max(r[field] for r in rows),
                                          'unit': 'Pa gauge' if field == 'pressure' else 'm/s',
                                          'location': 'boundary surfaces'}
        figure = plt.figure(figsize=(9, 7))
        axis = figure.add_subplot(projection='3d')
        cloud = axis.scatter([r['x_m'] for r in rows], [r['y_m'] for r in rows], [r['z_m'] for r in rows], c=[r[field] for r in rows], s=5)
        unit = 'Pa gauge' if field == 'pressure' else 'm/s'
        figure.colorbar(cloud, ax=axis, label=field + ' (' + unit + ')')
        axis.set(xlabel='X (m)', ylabel='Y (m)', zlabel='Z (m)', title='Fluent boundary surface field')
        figure.savefig(self.artifact(name + '.png'), dpi=140); plt.close(figure)
        self.report['images'].append({'file': name + '.png', 'label': field + ' (' + unit + ') · boundary surface'})

    def close(self):
        session = self.solver or self.meshing
        if session:
            session.exit()


def run(request, directory, context_factory=ExecutionContext):
    validate_request(request)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    program = request['program']
    (directory / 'agent.py').write_text(program['code'], encoding='utf-8')
    (directory / 'source.step').write_bytes(Path(request['stepFile']).read_bytes())
    report = {'kind': 'generated-python', 'solver': 'fluent', 'status': 'failed', 'converged': False,
              'modelId': request['modelId'], 'title': program['title'],
              'programSHA256': hashlib.sha256(program['code'].encode()).hexdigest(),
              'analysis': request.get('analysis'), 'executionMode':'agent-authored-v2',
              'verifiedSolves': [], 'results': {}, 'metrics': {},
              'tables': {}, 'images': [], 'limitations': [
                   'Agent-authored meshing, physics, materials and conditions; no fixed CFD setup template.',
                   'Checked steady-flow solving in one fluid cell zone, 32000 cells, 2000 total requested iterations, one CPU; no automatic FSI.',
                  'Geometric correspondence uses finite sampling; convergence is not mesh independence or physical validation.']}
    output = io.StringIO()
    from mechanical.agent_run import Tee
    ctx = context_factory(request, directory, report)
    try:
        with contextlib.redirect_stdout(Tee(sys.stdout,output)), contextlib.redirect_stderr(Tee(sys.stderr,output)):
            ctx.prepare()
            exec(compile(program['code'], 'agent.py', 'exec'),
                 {'ctx':ctx,'meshing':ctx.meshing,'workflow':ctx.meshing.workflow,'tasks':ctx.tasks})
        if report['verifiedSolves'] and not report['converged']:
            raise ValueError('The Fluent solution has not met the agreed convergence criteria.')
        if ctx.solver is not None:
            ctx.save_case()
        report['status'] = 'succeeded'
        report.pop('errorStage', None)
    except Exception as exc:
        report.update(error=str(exc), traceback=traceback.format_exc())
    finally:
        if ctx._iterated and not (directory / 'case.cas.h5').is_file():
            try:
                ctx.save_case()
            except Exception as exc:
                report.setdefault('messages', []).append('Native Fluent export: ' + str(exc))
        try:
            ctx.close()
        except Exception as exc:
            report.setdefault('messages', []).append('Fluent cleanup: ' + str(exc))
        report['stdout'] = output.getvalue()[-100000:]
        write_json(directory / 'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    report = run(json.loads(args.request.read_text(encoding='utf-8')), args.output_dir)
    return 0 if report['status'] == 'succeeded' else 1


if __name__ == '__main__':
    raise SystemExit(main())
