import base64
from concurrent.futures import ThreadPoolExecutor
import io
import json
import time
import unittest
import uuid

from PIL import Image
import test_mechanical
from gradio_app.chat_agent import ChatAgent
from gradio_app.chat_confirmations import propose
from gradio_app.chat_state import ChatWorkspace
from gradio_app.chat_tools import apply_tool, tool_schemas


class VisualModeTests(unittest.TestCase):
    def setUp(self):
        fixture = test_mechanical.RequestTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.workspace, self.mid = fixture.workspace, fixture.mid
        self.service = ChatWorkspace(self.workspace)
        self.sid = uuid.uuid4().hex
        self.service.open_model(self.sid, self.workspace.get(self.mid))
        self.keys = [f['key'] for f in self.workspace.get(self.mid)['faces']]
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.addCleanup(self.pool.shutdown)
        self.service.visual.timeout = 2
        buf = io.BytesIO()
        Image.new('RGB', (80, 60), '#00ae60').save(buf, format='PNG')
        self.image = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()

    def preferences(self, mode='guided', visual=True):
        c = self.service.context(self.sid)
        self.service.preferences(self.sid, c['revision'], mode, visual)

    def start(self, tool, **args):
        c = self.service.context(self.sid)
        future = self.pool.submit(apply_tool, self.service, self.sid, tool,
                                  dict(model_id=self.mid, revision=c['revision'], **args))
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            request = self.service.context(self.sid)['visualAssistance']['request']
            if request:
                return future, request
            time.sleep(.005)
        self.fail('No browser request was published')

    def capture(self):
        future, request = self.start('capture_viewport', view='current')
        self.service.visual.respond(self.sid, request['id'], {'model_id': self.mid, 'image': self.image})
        return future.result(1)

    def test_defaults_and_mode_switch_cancel_pending_without_executing(self):
        c = self.service.context(self.sid)
        self.assertTrue(c['confirmationRequired'])
        self.assertFalse(c['visualAssistance']['enabled'])
        before = len(self.workspace.get(self.mid)['comments'])
        propose(self.service, self.sid, 'add_comment', dict(model_id=self.mid,
            revision=c['revision'], face_key=self.keys[0], text='Pending'), 'Proposed')
        self.preferences('autonomous', False)
        c = self.service.context(self.sid)
        self.assertFalse(c['confirmationRequired'])
        self.assertIsNone(c['pendingConfirmation'])
        self.assertEqual(len(self.workspace.get(self.mid)['comments']), before)
        self.assertNotIn('set_mode', [x['name'] for x in tool_schemas(True)])

    def test_autonomous_can_run_code_directly_or_ask_for_missing_details(self):
        self.preferences('autonomous', False)
        calls = []
        self.service.code_runner = lambda w, m, p, s: (calls.append(p) or {'images': [], 'report': {
            'kind': 'generated-python', 'status': 'succeeded', 'verifiedSolves': [], 'tables': {}}})
        class Model:
            def complete(_, session, prompt):
                data = json.loads(prompt.split('CAD_REQUEST_JSON\n')[1])
                if data['conversation'][-1]['content'] == 'What load?':
                    return json.dumps({'reply': 'What force magnitude and direction should this represent?'})
                if data['toolObservationsThisTurn']:
                    return json.dumps({'reply': 'Inspection finished.'})
                c = data['context']
                return json.dumps({'reply': 'I will inspect the geometry.', 'action': {'tool': 'run_mechanical_code',
                    'arguments': {'model_id': c['modelId'], 'revision': c['revision'],
                                  'title': 'Inspect', 'objective': 'Geometry only', 'code': 'print(ctx.geometry)'}}})
        agent = ChatAgent(self.service, Model())
        list(agent.turn(self.sid, 'Inspect the CAD'))
        self.assertEqual(len(calls), 1)
        self.assertIsNone(self.service.session(self.sid).pending_confirmation)
        list(agent.turn(self.sid, 'What load?'))
        self.assertEqual(len(calls), 1)
        self.assertIn('magnitude', self.service.session(self.sid).messages[-1]['content'])

    def test_screenshot_without_click_then_exact_face_pick_preserves_selection(self):
        self.preferences()
        self.service.select(self.sid, self.mid, self.keys[0])
        frame = self.capture()
        self.assertEqual((frame['width'], frame['height']), (80, 60))
        self.assertEqual(self.service.context(self.sid)['highlightedFaceKeys'], [])
        future, request = self.start('pick_viewport_face', frame_id=frame['frameId'], x=30, y=25)
        self.service.visual.respond(self.sid, request['id'], {'model_id': self.mid, 'face_key': self.keys[1]})
        self.assertEqual(future.result(1)['faceKey'], self.keys[1])
        c = self.service.context(self.sid)
        self.assertEqual(c['selectedFace']['key'], self.keys[0])
        self.assertEqual(c['highlightedFaceKeys'], [self.keys[1]])
        self.assertTrue(c['confirmationRequired'])
        self.assertIsNone(c['visualAssistance']['frame'])  # Highlights changed; fresh image required.

    def test_visual_assistance_does_not_invalidate_a_guided_confirmation(self):
        self.preferences()
        c = self.service.context(self.sid)
        before = len(self.workspace.get(self.mid)['comments'])
        propose(self.service, self.sid, 'add_comment', dict(model_id=self.mid,
            revision=c['revision'], face_key=self.keys[0], text='Confirmed note'), 'Review this face.')
        class Model:
            def complete(_, session, prompt):
                return json.dumps({'reply': 'The confirmed note is saved.'})
        list(ChatAgent(self.service, Model()).turn(self.sid, 'Confirm'))
        self.assertEqual(len(self.workspace.get(self.mid)['comments']), before + 1)
        self.assertIsNone(self.service.context(self.sid)['pendingConfirmation'])

    def test_off_stale_wrong_model_and_invalid_pixels_cannot_pick(self):
        c = self.service.context(self.sid)
        with self.assertRaisesRegex(ValueError, 'off'):
            apply_tool(self.service, self.sid, 'capture_viewport', dict(model_id=self.mid, revision=c['revision']))
        self.preferences()
        frame = self.capture()
        c = self.service.context(self.sid)
        for x, y in [(80, 0), (0, 60), (-1, 1), (float('nan'), 1)]:
            with self.assertRaises(ValueError):
                apply_tool(self.service, self.sid, 'pick_viewport_face', dict(model_id=self.mid,
                    revision=c['revision'], frame_id=frame['frameId'], x=x, y=y))
        self.service.select(self.sid, self.mid, self.keys[0])
        c = self.service.context(self.sid)
        with self.assertRaisesRegex(ValueError, 'stale'):
            apply_tool(self.service, self.sid, 'pick_viewport_face', dict(model_id=self.mid,
                revision=c['revision'], frame_id=frame['frameId'], x=30, y=25))
        future, request = self.start('capture_viewport')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.service.visual.respond(self.sid, request['id'], {'model_id': 'another-model', 'image': self.image})
        with self.assertRaisesRegex(ValueError, 'changed'):
            future.result(1)
        self.preferences(visual=False)
        self.assertIsNone(self.service.session(self.sid).visual_frame)

    def test_background_miss_timeout_and_bad_image_do_not_change_geometry(self):
        self.preferences()
        frame = self.capture()
        future, request = self.start('pick_viewport_face', frame_id=frame['frameId'], x=1, y=1)
        self.service.visual.respond(self.sid, request['id'], {'model_id': self.mid, 'face_key': None})
        self.assertIsNone(future.result(1)['faceKey'])
        self.assertEqual(self.service.context(self.sid)['highlightedFaceKeys'], [])
        future, request = self.start('capture_viewport')
        with self.assertRaises(ValueError):
            self.service.visual.respond(self.sid, request['id'], {'model_id': self.mid, 'image': 'not an image'})
        with self.assertRaises(ValueError):
            future.result(1)
        self.service.visual.timeout = .01
        c = self.service.context(self.sid)
        with self.assertRaisesRegex(ValueError, 'did not respond'):
            apply_tool(self.service, self.sid, 'capture_viewport', dict(model_id=self.mid, revision=c['revision']))
        self.assertIsNone(self.service.context(self.sid)['visualAssistance']['request'])
