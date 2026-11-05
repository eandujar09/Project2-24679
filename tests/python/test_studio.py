"""Presentation routes preserve the chat gate and private artifact boundaries."""
import json
import time
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import test_mechanical
from gradio_app.chat_state import ChatWorkspace
from gradio_app.studio import install_studio


class StudioTests(unittest.TestCase):
    def setUp(self):
        fixture = test_mechanical.RequestTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.workspace, self.mid = fixture.workspace, fixture.mid
        self.service = ChatWorkspace(self.workspace)
        self.calls = []
        calls = self.calls
        class Model:
            def complete(_, session, prompt):
                data = json.loads(prompt.split('CAD_REQUEST_JSON\n', 1)[1])
                if data['toolObservationsThisTurn']:
                    return json.dumps({'reply': 'Finished.', 'action': None})
                c = data['context']
                calls.append(c['sessionId'])
                return json.dumps({'reply': 'Please check this proposed note.', 'action': {
                    'tool': 'add_comment', 'arguments': {'model_id': c['modelId'],
                    'revision': c['revision'], 'face_key': c['faces'][0]['key'], 'text': 'Reviewed face'}}})
        server = FastAPI()
        install_studio(server, self.service, Model())
        self.client = TestClient(server)
        self.addCleanup(self.client.close)
        self.sid = self.client.post('/api/studio/sessions').json()['context']['sessionId']
        self.base = '/api/studio/sessions/' + self.sid
        self.client.post(self.base + '/open', json={'model_id': self.mid}).raise_for_status()

    def read(self):
        return self.client.get(self.base).json()

    def settled(self):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            data = self.read()
            if not data['busy']:
                return data
            time.sleep(.01)
        self.fail('Chat turn did not finish')

    def test_exact_confirmation_and_idempotent_retries(self):
        before = len(self.workspace.get(self.mid)['comments'])
        message = {'text': 'Add a note to this face', 'request_id': 'first'}
        self.assertEqual(self.client.post(self.base + '/messages', json=message).status_code, 202)
        data = self.settled()
        self.assertEqual(len(self.workspace.get(self.mid)['comments']), before)
        self.assertTrue(data['proposalToken'])
        self.client.post(self.base + '/messages', json=message).raise_for_status()
        self.assertEqual(len(self.calls), 1)
        response = self.client.post(self.base + '/messages', json={
            'text': 'Confirm', 'request_id': 'stale', 'proposal_token': 'old-token'})
        self.assertEqual(response.status_code, 409)
        self.client.post(self.base + '/messages', json={
            'text': 'Confirm', 'request_id': 'confirm', 'proposal_token': data['proposalToken']}).raise_for_status()
        self.settled()
        self.assertEqual(len(self.workspace.get(self.mid)['comments']), before + 1)

    def test_stale_selection_unknown_session_and_foreign_origin(self):
        self.assertEqual(self.client.get('/api/studio/sessions/missing').status_code, 404)
        response = self.client.post(self.base + '/select', json={'model_id': 'old-model', 'face_key': None})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.post('/api/studio/sessions', headers={'Origin': 'https://unrelated.example'}).status_code, 403)
        self.assertEqual(self.client.get(self.base + '/geometry', params={'model_id': 'old-model'}).status_code, 409)
        self.assertEqual(self.client.post(self.base + '/upload', files={'file': ('code.py', b'print(1)')}).status_code, 422)

    def test_preferences_are_explicit_idle_only_and_isolated_per_window(self):
        c = self.read()['context']
        settings = {'revision': c['revision'], 'interaction_mode': 'autonomous', 'visual_enabled': True}
        self.service.session(self.sid).busy = True
        self.assertEqual(self.client.post(self.base + '/preferences', json=settings).status_code, 409)
        self.service.session(self.sid).busy = False
        self.assertEqual(self.client.post(self.base + '/preferences', json=dict(settings, interaction_mode='invalid')).status_code, 422)
        result = self.client.post(self.base + '/preferences', json=settings)
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json()['context']['confirmationRequired'])
        self.assertTrue(result.json()['context']['visualAssistance']['enabled'])
        self.assertEqual(self.client.post(self.base + '/preferences', json=settings).status_code, 409)
        other = self.client.post('/api/studio/sessions').json()['context']
        self.assertTrue(other['confirmationRequired'])
        self.assertFalse(other['visualAssistance']['enabled'])

    def test_artifacts_are_scoped_and_clear_preserves_execution_records(self):
        exports = self.workspace.root / 'exports'
        exports.mkdir(exist_ok=True)
        artifact = exports / 'result.txt'
        artifact.write_text('real artifact bytes')
        private = self.workspace.root / 'private.txt'
        private.write_text('private content')
        s = self.service.existing(self.sid)
        s.messages.extend([{'role': 'assistant', 'content': {'image': str(artifact), 'label': 'Result'}},
                           {'role': 'assistant', 'content': {'image': str(private), 'label': 'Invalid'}}])
        s.program_attempts = [{'status': 'unknown', 'title': 'Uncertain job', 'recoverable': True}]
        data = self.read()
        url = data['messages'][-2]['content']['image']
        self.assertEqual(self.client.get(url).text, 'real artifact bytes')
        self.assertIn('unavailable', data['messages'][-1]['content'])
        other = self.client.post('/api/studio/sessions').json()['context']['sessionId']
        self.assertEqual(self.client.get(url.replace(self.sid, other)).status_code, 404)
        self.client.post(self.base + '/clear').raise_for_status()
        self.assertEqual(self.read()['context']['programAttempts'][0]['status'], 'unknown')
