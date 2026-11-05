import json
from pathlib import Path
import threading
import unittest
import uuid

from gradio_app.chat_state import ChatWorkspace
from gradio_app.chat_agent import ChatAgent
from gradio_app.chat_tools import apply_tool
import test_mechanical


def fake_result(workspace, model_id, size):
    directory = workspace.root / 'exports' / ('fake-' + uuid.uuid4().hex)
    directory.mkdir()
    archive = directory / 'simulation.zip'
    archive.write_bytes(b'Synthetic test; not an Ansys result')
    return {'report': {'status': 'succeeded', 'modelId': model_id, 'syntheticTest': True,
                      'results': {'totalDeformation': {'maximum': 0.1, 'unit': 'mm'},
                                  'vonMisesStress': {'maximum': 2, 'unit': 'MPa'}}},
            'directory': directory, 'archive': str(archive), 'images': []}


class ChatTests(unittest.TestCase):
    def setUp(self):
        fixture = test_mechanical.RequestTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.workspace, self.mid = fixture.workspace, fixture.mid
        self.calls = []
        def runner(*args):
            self.calls.append(args)
            return fake_result(*args)
        self.service = ChatWorkspace(self.workspace, runner=runner)
        self.sid = uuid.uuid4().hex
        self.service.open_model(self.sid, self.workspace.get(self.mid))
        self.keys = [f['key'] for f in self.workspace.get(self.mid)['faces']]

    def action(self, name, **kwargs):
        c = self.service.context(self.sid)
        return apply_tool(self.service, self.sid, name, dict(model_id=c['modelId'], revision=c['revision'], **kwargs))

    def test_selection_resource_and_highlight_are_independent(self):
        self.service.select(self.sid, self.mid, self.keys[0])
        self.action('highlight_faces', face_keys=[self.keys[1]], focus=True)
        c = self.service.context(self.sid)
        self.assertEqual(c['selectedFace']['key'], self.keys[0])
        self.assertEqual(c['highlightedFaceKeys'], [self.keys[1]])
        state = json.loads(self.service.viewer(self.sid))
        self.assertEqual(state['selected'], self.keys[0])
        self.assertEqual(state['highlighted'], [self.keys[1]])
        self.assertEqual(state['focusFace'], self.keys[1])

    def test_stale_selection_and_invented_face_cannot_mutate(self):
        c = self.service.context(self.sid)
        self.service.select(self.sid, self.mid, self.keys[2])
        before = self.workspace.get(self.mid)['boundaryConditions']
        with self.assertRaisesRegex(ValueError, 'state changed'):
            apply_tool(self.service, self.sid, 'apply_condition', dict(model_id=self.mid, revision=c['revision'],
                       face_key=self.keys[2], kind='fixed', values={}))
        with self.assertRaises(ValueError):
            self.action('highlight_faces', face_keys=['invented-face'])
        self.assertEqual(before, self.workspace.get(self.mid)['boundaryConditions'])

    def test_windows_have_separate_selection_and_shared_model_revision(self):
        second = uuid.uuid4().hex
        self.service.open_model(second, self.workspace.get(self.mid))
        old = self.service.context(second)['revision']
        self.service.select(self.sid, self.mid, self.keys[0])
        self.assertIsNone(self.service.context(second)['selectedFace'])
        self.action('add_comment', face_key=self.keys[0], text='Note')
        self.assertGreater(self.service.context(second)['revision'], old)

    def test_missing_assumptions_and_unsupported_material_block_solver(self):
        with self.assertRaisesRegex(ValueError, 'Setup incomplete'):
            self.action('run_simulation')
        with self.assertRaises(ValueError):
            self.action('set_analysis', material='Aluminum', small_deformation=True)
        self.assertEqual(self.calls, [])

    def test_ready_setup_runs_once_and_same_input_is_not_resubmitted(self):
        self.action('set_analysis', material='Structural Steel', small_deformation=True)
        self.action('run_simulation')
        result = self.action('run_simulation')
        self.assertTrue(result['alreadyRun'])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.service.context(self.sid)['lastResult']['status'], 'succeeded')

    def test_changed_analysis_clears_current_result_and_can_run_new_snapshot(self):
        self.action('set_analysis', material='Structural Steel', small_deformation=True)
        self.action('run_simulation')
        self.action('set_analysis', material='Structural Steel', small_deformation=True, element_size_mm=2)
        self.assertIsNone(self.service.context(self.sid)['lastResult'])
        self.action('run_simulation')
        self.assertEqual(len(self.calls), 2)

    def test_repeated_force_action_cannot_silently_double_the_load(self):
        before = self.workspace.get(self.mid)['boundaryConditions']
        load = next(r for r in before if r['type'] == 'force')
        with self.assertRaisesRegex(ValueError, 'adding it twice'):
            self.action('apply_condition', face_key=load['faceKey'], kind='force', values=load['values'])
        self.assertEqual(before, self.workspace.get(self.mid)['boundaryConditions'])

    def test_chat_agent_executes_tools_then_reports_actual_results(self):
        class Model:
            def complete(_, session, prompt):
                c = json.loads(prompt.split('CAD_REQUEST_JSON\n', 1)[1])['context']
                args = {'model_id': c['modelId'], 'revision': c['revision']}
                if c['analysis']['material'] is None:
                    name = 'set_analysis'
                    args.update(material='Structural Steel', small_deformation=True)
                elif c['lastResult'] is None:
                    name = 'run_simulation'
                else:
                    return json.dumps({'reply': 'The returned report is ready.', 'action': None})
                return json.dumps({'reply': 'Working on it.', 'action': {'tool': name, 'arguments': args}})
        agent = ChatAgent(self.service, Model())
        list(agent.turn(self.sid, 'Run this steel small-deformation test.'))
        self.assertIsNone(self.service.session(self.sid).material)
        self.assertEqual(self.calls, [])
        list(agent.turn(self.sid, 'Confirm'))
        self.assertEqual(self.service.session(self.sid).material, 'Structural Steel')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.service.session(self.sid).pending_confirmation['tool'], 'run_simulation')
        list(agent.turn(self.sid, 'Confirm'))
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(any('Simulation complete' in m['content'] for m in self.service.session(self.sid).messages))
        self.assertFalse(self.service.session(self.sid).busy)

    def test_model_switch_resets_context_and_unknown_session_is_not_created_by_resource_read(self):
        with self.assertRaisesRegex(ValueError, 'not found'):
            self.service.context(uuid.uuid4().hex)
        self.service.select(self.sid, self.mid, self.keys[0])
        self.action('set_analysis', material='Structural Steel', small_deformation=True)
        self.service.open_model(self.sid, self.workspace.get(self.mid))
        c = self.service.context(self.sid)
        self.assertIsNone(c['selectedFace'])
        self.assertIsNone(c['analysis']['material'])

    def test_live_mcp_reads_state_and_controls_highlights(self):
        from starlette.testclient import TestClient
        from gradio_app.app import build_server
        app = build_server(self.workspace, service=self.service)
        with TestClient(app, base_url='http://127.0.0.1:7860') as client:
            def rpc(method, params=None):
                response = client.post('/mcp/', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}},
                                       headers={'Accept': 'application/json, text/event-stream'})
                self.assertEqual(response.status_code, 200, response.text)
                data = response.json()
                self.assertNotIn('error', data)
                return data['result']
            rpc('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'cad-test', 'version': '1'}})
            templates = rpc('resources/templates/list')['resourceTemplates']
            self.assertTrue(any('/context' in t['uriTemplate'] for t in templates))
            self.service.select(self.sid, self.mid, self.keys[0])
            result = rpc('resources/read', {'uri': f'cad://session/{self.sid}/context'})
            context = json.loads(result['contents'][0]['text'])
            self.assertEqual(context['selectedFace']['key'], self.keys[0])
            action = rpc('tools/call', {'name': 'highlight_faces', 'arguments': {'session_id': self.sid,
                         'model_id': self.mid, 'revision': context['revision'], 'face_keys': [self.keys[1]], 'focus': True}})
            self.assertFalse(action.get('isError', False))
            self.assertEqual(json.loads(self.service.viewer(self.sid))['highlighted'], [self.keys[1]])
            self.assertEqual(self.service.context(self.sid)['selectedFace']['key'], self.keys[0])
            models = rpc('resources/read', {'uri': 'cad://models'})
            self.assertEqual(json.loads(models['contents'][0]['text'])[0]['modelId'], self.mid)
            stale = rpc('tools/call', {'name': 'open_saved_model', 'arguments': {
                'session_id': self.sid, 'model_id': self.mid, 'revision': context['revision']}})
            self.assertTrue(stale.get('isError'))
            opened = rpc('tools/call', {'name': 'open_saved_model', 'arguments': {
                'session_id': self.sid, 'model_id': self.mid,
                'revision': self.service.context(self.sid)['revision']}})
            self.assertFalse(opened.get('isError', False))
            self.assertEqual(self.service.context(self.sid)['modelId'], self.mid)
            self.assertIsNone(self.service.context(self.sid)['selectedFace'])
