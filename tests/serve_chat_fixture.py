"""Local-only browser-test server with a scripted model and synthetic solver."""
from pathlib import Path
import json
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gradio_app.app import build_server
from gradio_app.backend import Workspace
from gradio_app.chat_state import ChatWorkspace
from PIL import Image, ImageDraw
import uvicorn

class ScriptedTestModel:
    def complete_visual(self, session, prompt, frame):
        assert frame['image'].startswith('data:image/png;base64,')
        return self.complete(session, prompt)

    def complete(self, session, prompt):
        data = json.loads(prompt.split('CAD_REQUEST_JSON\n', 1)[1])
        c = data['context']
        text = data['conversation'][-1]['content'].lower()
        if data['toolObservationsThisTurn']:
            last = data['toolObservationsThisTurn'][-1]
            if last.get('tool') == 'suggest_fluid_domain' and last['ok']:
                return json.dumps({'reply':'Use this suggested geometric gap?','action':{'tool':'set_fluid_domain','arguments':{
                    'model_id':c['modelId'],'revision':c['revision'],'kind':'box','cad_role':'obstacle',
                    'parameters':last['result']['parameters'],'description':'User-selected suggested geometric gap; not a CFD sizing guarantee.'}}})
            return json.dumps({'reply': 'Done. The setup is saved.' if last['ok'] else 'More information is needed: ' + last['error'], 'action': None})
        args = {'model_id': c['modelId'], 'revision': c['revision']}
        name = None
        if text.startswith('add a box enclosure around'):
            return json.dumps({'reply':'Choose the enclosure sizing.','details':'A positive gap prevents contact but does not prove CFD domain-size independence.',
                              'choices':[{'label':'Suggest clearance','value':'Suggest a positive geometric clearance on all sides.'},
                                         {'label':'Enter dimensions','value':'I will enter custom box bounds.'}]})
        elif text.startswith('suggest a positive geometric clearance'):
            name = 'suggest_fluid_domain'; args.update(fixed_axes=[])
        elif text.startswith('create the saved fluid domain geometry'):
            name = 'create_fluid_domain'
        elif text.strip() in ('mechanical', 'heat transfer', 'fluid dynamics'):
            name = 'set_simulation_intent'; args.update(simulation_type={'mechanical':'mechanical','heat transfer':'heat_transfer','fluid dynamics':'fluid'}[text.strip()])
        elif text.startswith('define demo pipe domain'):
            name = 'set_fluid_domain'; args.update(kind='cylinder',cad_role='reference',
                parameters=dict(origin_x=0,origin_y=0,origin_z=0,axis_x=0,axis_y=0,axis_z=1,radius=10,length=50),
                description='Synthetic user-defined cylindrical internal flow domain; preparation required.')
        elif text.startswith('apply demo temperature'):
            name = 'apply_condition'; args.update(face_key=c['selectedFace']['key'],kind='temperature',values={'temperature':80})
        elif text.startswith('apply demo heat flux'):
            name = 'apply_condition'; args.update(face_key=c['selectedFace']['key'],kind='heat_flux',values={'magnitude':500})
        elif text.startswith('apply demo convection'):
            name = 'apply_condition'; args.update(face_key=c['selectedFace']['key'],kind='convection',values={'coefficient':15,'ambient_temperature':25})
        elif text.startswith('apply demo radiation'):
            name = 'apply_condition'; args.update(face_key=c['selectedFace']['key'],kind='radiation',values={'emissivity':.8,'ambient_temperature':20})
        elif text.startswith('apply demo insulation'):
            name = 'apply_condition'; args.update(face_key=c['selectedFace']['key'],kind='adiabatic',values={})
        elif text.startswith('inspect screenshot'):
            frame = c['visualAssistance']['frame']
            return json.dumps({'reply': 'I received the viewport screenshot: ' + str(frame['width']) + ' pixels wide. No click was needed.', 'action': None})
        if text.startswith('pick screenshot center'):
            frame = c['visualAssistance']['frame']
            name = 'pick_viewport_face'; args.update(frame_id=frame['id'], x=frame['width']/2, y=frame['height']/2)
        elif text.startswith('compare mesh sizes'):
            name = 'run_mechanical_code'; args.update(title='Generated mesh study', objective='Synthetic browser fixture', code="for size in [6, 4, 3]:\n    print(size)\n")
        elif text.startswith('enable gravity') or text.startswith('reverse gravity') or text.startswith('disable gravity'):
            direction = 'PositiveZAxis' if text.startswith('reverse') else 'NegativeZAxis'
            code = "analysis = Model.AddStaticStructuralAnalysis()\ng = analysis.AddEarthGravity()\ng.Direction = GravityOrientationType." + direction + "\n"
            if text.startswith('disable'):
                code += 'g.Suppressed = True\n'
            name = 'run_mechanical_code'; args.update(title='Gravity setup', objective='Synthetic gravity viewport fixture', code=code)
        elif text.startswith('fix this face'):
            name = 'apply_condition'; args.update(face_key=c['selectedFace']['key'], kind='fixed', values={})
        elif text.startswith('fix the back face'):
            face = next(f for f in c['faces'] if f['index'] == 7)
            name = 'apply_condition'; args.update(face_key=face['key'], kind='fixed', values={})
        elif text.startswith('highlight face 2'):
            name = 'highlight_faces'; args.update(face_keys=[f['key'] for f in c['faces'] if f['index'] == 2], focus=True)
        elif text.startswith('apply 100 n'):
            name = 'apply_condition'; args.update(face_key=c['selectedFace']['key'], kind='force', values={'x': 0, 'y': 0, 'z': 100})
        elif text.startswith('change force to 200 n'):
            original = next(row for row in c['boundaryConditions'] if row['type'] == 'force')
            name = 'apply_condition'; args.update(face_key=original['faceKey'], record_id=original['id'],
                                                 kind='force', values={'x': 0, 'y': 0, 'z': 200})
        elif text.startswith('use structural steel'):
            name = 'set_analysis'; args.update(material='Structural Steel', small_deformation=True)
        elif text.startswith('configure demo fluid'):
            name = 'set_fluent_analysis'; args.update(domain='fluid-volume', regime='steady-laminar-incompressible',
                density=1, dynamic_viscosity=0.001, operating_pressure=101325, mesh_size_mm=3,
                max_iterations=100, residual_tolerance=1e-5, mass_imbalance_tolerance=0.01)
        elif text.startswith('apply demo inlet'):
            name = 'apply_condition'; args.update(face_key=c['selectedFace']['key'],kind='velocity_inlet',values=dict(x=0,y=0,z=0.01))
        elif text.startswith('apply demo outlet'):
            name = 'apply_condition'; args.update(face_key=c['selectedFace']['key'],kind='pressure_outlet',values={'gauge_pressure':0})
        elif text.startswith('apply demo wall'):
            name = 'apply_condition'; args.update(face_key=c['selectedFace']['key'],kind='wall',values={})
        elif text.startswith('run fluent simulation'):
            name = 'run_fluent_code'; args.update(title='SYNTHETIC Fluent UI fixture',objective='Browser presentation only; no real CFD result.',
                                                  code='solver = ctx.generate_mesh()\nctx.solve()')
        elif text.startswith('run simulation'):
            name = 'run_simulation'
        if name:
            return json.dumps({'reply': 'Working on your request.', 'action': {'tool': name, 'arguments': args}})
        return json.dumps({'reply': 'I can see your selected face. What support or load should it have?', 'action': None})


def synthetic_solver(workspace, model_id, size):
    folder = workspace.root / 'exports' / ('synthetic-' + uuid.uuid4().hex)
    folder.mkdir()
    images = []
    for name in ('totalDeformation', 'vonMisesStress'):
        path = folder / (name + '.png')
        image = Image.new('RGB', (500, 260), '#203047')
        ImageDraw.Draw(image).text((25, 110), 'SYNTHETIC UI TEST - ' + name, fill='white')
        image.save(path)
        images.append(str(path))
    archive = folder / 'simulation.zip'
    archive.write_bytes(b'Synthetic UI test archive; not an engineering result.')
    native = folder / 'setup.mechdat'
    native.write_bytes(b'Synthetic UI test setup; not a Mechanical database.')
    solved = folder / 'simulation.mechpz'
    solved.write_bytes(b'Synthetic UI test archive; not a Mechanical archive.')
    return {'directory': folder, 'archive': str(archive), 'images': images,
            'mechanicalFile': str(native), 'mechanicalArchive': str(solved),
            'report': {'status': 'succeeded', 'modelId': model_id, 'syntheticTest': True,
                       'nativeArchive': {'includesResults': True},
                       'results': {'totalDeformation': {'maximum': 0.12, 'unit': 'mm'},
                                   'vonMisesStress': {'maximum': 18.4, 'unit': 'MPa'}}}}

workspace = Workspace(sys.argv[1])
def synthetic_code(workspace, model_id, program, selected_face):
    result = synthetic_solver(workspace, model_id, 3)
    code = result['directory'] / 'agent.py'
    code.write_text(program['code'])
    result['codeFile'] = str(code)
    result['report'].update(kind='generated-python', title=program['title'], verifiedSolves=[{'status': 'Done'}]*3,
        tables={'Synthetic mesh comparison': [{'size_mm': n, 'nodes': 1000*i} for i,n in enumerate([6,4,3], 1)]},
        images=[{'file': Path(path).name, 'label': 'SYNTHETIC UI TEST'} for path in result['images']])
    from mechanical.gravity import preview_gravity
    result['report']['gravityLoads'] = [dict(row, source='mechanical') for row in preview_gravity(program['code'])]
    return result

def synthetic_fluent(workspace, model_id, program, selected_face):
    result = synthetic_code(workspace, model_id, program, selected_face)
    result.pop('mechanicalFile', None); result.pop('mechanicalArchive', None)
    result['report'].update(solver='fluent',converged=True,verifiedSolves=[{'status':'Done'}],
                            tables={'SYNTHETIC UI CFD CHECK': [{'fixture':'Not a real Fluent result'}]})
    result['report'].pop('nativeArchive', None)
    return result


service = ChatWorkspace(workspace, runner=synthetic_solver, code_runner=synthetic_code, fluent_runner=synthetic_fluent)
uvicorn.run(build_server(workspace, ScriptedTestModel(), service, studio='--studio' in sys.argv), host='127.0.0.1', port=7862)
