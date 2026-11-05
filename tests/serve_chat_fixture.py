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
            return json.dumps({'reply': 'Done. The setup is saved.' if last['ok'] else 'More information is needed: ' + last['error'], 'action': None})
        args = {'model_id': c['modelId'], 'revision': c['revision']}
        name = None
        if text.startswith('inspect screenshot'):
            frame = c['visualAssistance']['frame']
            return json.dumps({'reply': 'I received the viewport screenshot: ' + str(frame['width']) + ' pixels wide. No click was needed.', 'action': None})
        if text.startswith('pick screenshot center'):
            frame = c['visualAssistance']['frame']
            name = 'pick_viewport_face'; args.update(frame_id=frame['id'], x=frame['width']/2, y=frame['height']/2)
        elif text.startswith('compare mesh sizes'):
            name = 'run_mechanical_code'; args.update(title='Generated mesh study', objective='Synthetic browser fixture', code="for size in [6, 4, 3]:\n    print(size)\n")
        elif text.startswith('fix this face'):
            name = 'apply_condition'; args.update(face_key=c['selectedFace']['key'], kind='fixed', values={})
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
    return {'directory': folder, 'archive': str(archive), 'images': images,
            'report': {'status': 'succeeded', 'modelId': model_id, 'syntheticTest': True,
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
    return result

service = ChatWorkspace(workspace, runner=synthetic_solver, code_runner=synthetic_code)
uvicorn.run(build_server(workspace, ScriptedTestModel(), service, studio='--studio' in sys.argv), host='127.0.0.1', port=7862)
