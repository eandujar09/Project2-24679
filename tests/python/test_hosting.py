import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from gradio_app.app import build_server
from gradio_app.backend import Workspace
from gradio_app.hosting import hosting_settings


class HostingTests(unittest.TestCase):
    def test_network_listener_requires_login_and_private_address(self):
        self.assertIsNone(hosting_settings('127.0.0.1'))
        for host in ('0.0.0.0', '192.168.1.10', '8.8.8.8', '::'):
            with self.assertRaises(ValueError):
                hosting_settings(host)
        with self.assertRaisesRegex(ValueError, 'requires --auth-config'):
            hosting_settings('100.88.230.43')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'auth.json'
            path.write_text(json.dumps({'username': 'demo', 'password': 'test:only'}))
            self.assertEqual(hosting_settings('100.88.230.43', path),
                             {'username': 'demo', 'password': 'test:only'})
            path.write_text(json.dumps({'username': 'demo', 'password': ''}))
            with self.assertRaises(ValueError):
                hosting_settings('100.88.230.43', path)

    def test_auth_covers_frontend_gradio_mcp_and_files(self):
        with tempfile.TemporaryDirectory() as folder:
            server = build_server(Workspace(folder), auth={'username': 'demo', 'password': 'test:only'},
                                  hosted_host='100.88.230.43')
            with TestClient(server, base_url='http://100.88.230.43:7860') as client:
                for path in ('/', '/api/studio/sessions', '/mcp/', '/gradio_api/config',
                             '/studio-assets/private.js', '/api/studio/sessions/test/files/secret'):
                    self.assertEqual(client.get(path).status_code, 401, path)
                    self.assertEqual(client.get(path, auth=('demo', 'wrong')).status_code, 401, path)
                self.assertEqual(client.post('/api/studio/sessions').status_code, 401)
                self.assertEqual(client.get('/', headers={'Authorization': 'Basic !!'}).status_code, 401)
                self.assertIn('Basic', client.get('/').headers['www-authenticate'])
                session = client.post('/api/studio/sessions', auth=('demo', 'test:only'))
                self.assertEqual(session.status_code, 200)
                request = {'jsonrpc': '2.0', 'id': 1, 'method': 'resources/read', 'params': {'uri': 'cad://sessions'}}
                headers = {'Accept': 'application/json, text/event-stream'}
                response = client.post('/mcp/', json=request, headers=headers, auth=('demo', 'test:only'))
                self.assertEqual(response.status_code, 200)
                self.assertIn(session.json()['context']['sessionId'], response.text)
                headers['Host'] = 'untrusted.invalid'
                self.assertEqual(client.post('/mcp/', json=request, headers=headers,
                                             auth=('demo', 'test:only')).status_code, 421)
