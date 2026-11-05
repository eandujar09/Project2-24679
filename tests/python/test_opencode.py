"""Exercise HTTP transfer and disconnect handling without contacting a real host."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from mechanical.opencode_connection import OpenCodeAPI, OpenCodeConnection


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []
        self.files = {}
        calls, files = self.calls, self.files

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                from urllib.parse import urlsplit, parse_qs
                url = urlsplit(self.path)
                calls.append((self.command, self.path, self.headers.get("Authorization")))
                if url.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/must-not-follow")
                    self.end_headers()
                    return
                if self.headers.get("Authorization") != "Basic " + base64.b64encode(b"test-user:test-password").decode():
                    self.send_response(401)
                    self.end_headers()
                    return
                if self.command == "POST":
                    data = self.rfile.read(int(self.headers["Content-Length"]))
                    files[parse_qs(url.query)["path"][0]] = data
                    data, content_type = b'{"data": {"ok": true}}', "application/json"
                else:
                    data = files[url.path.removeprefix("/api/fs/read/")]
                    content_type = "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = handle_request

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.config = self.root / "login.json"
        self.config.write_text(json.dumps({"url": f"http://127.0.0.1:{server.server_port}",
                                           "username": "test-user", "password": "test-password"}))
        self.api = OpenCodeAPI(self.config, location=r"C:\worker")

    def test_authenticated_binary_round_trip_and_location(self):
        payload = bytes(range(256)) * 40
        self.api.write_file("sample.zip", payload)
        target = self.root / "download.zip"
        self.api.read_file("sample.zip", target)
        self.assertEqual(target.read_bytes(), payload)
        self.assertTrue(all("location%5Bdirectory%5D=C%3A%5Cworker" in c[1] for c in self.calls))
        self.assertFalse(target.with_suffix(".zip.part").exists())

    def test_redirect_does_not_forward_login_and_auth_failure_is_clear(self):
        with self.assertRaisesRegex(ValueError, "HTTP 302"):
            self.api.json("/redirect")
        self.assertEqual(len(self.calls), 1)
        self.api._authorization = "Basic invalid-test-credentials"
        with self.assertRaisesRegex(ValueError, "rejected the login"):
            self.api.json("/api/info")

    def test_download_limit_and_paths_leave_no_partial_result(self):
        self.files["sample.zip"] = b"abcd"
        target = self.root / "download.zip"
        with self.assertRaisesRegex(ValueError, "transfer limit"):
            self.api.read_file("sample.zip", target, max_bytes=3)
        self.assertFalse(target.exists())
        self.assertFalse(target.with_suffix(".zip.part").exists())
        for path in ("../escape", "/absolute", "C:/escape", "dir\\escape"):
            with self.assertRaises(ValueError):
                self.api.read_file(path)

    def test_disconnect_keeps_shell_id_without_resubmitting(self):
        connection = OpenCodeConnection(r"C:\worker", r"C:\worker\python.exe", self.config)
        record = self.root / "remote-job.json"
        record.write_text(json.dumps({"jobId": "a" * 32}))
        with patch.object(connection.api, "write_file"), \
             patch.object(connection.api, "start_shell", return_value={"id": "sh_test", "status": "running"}) as start, \
             patch.object(connection.api, "wait_shell", side_effect=TimeoutError("network interrupted")):
            with self.assertRaisesRegex(ValueError, "may still be running"):
                connection.run(b"test", record)
        self.assertEqual(start.call_count, 1)
        self.assertEqual(json.loads(record.read_text())["shellId"], "sh_test")

    def test_transient_status_read_recovers_without_starting_another_command(self):
        with patch.object(self.api, 'shell_info', side_effect=[ValueError('Cannot reach the OpenCode API.'),
                 {'id': 'known', 'status': 'exited', 'exit': 0}]) as read, \
             patch.object(self.api, 'start_shell') as submit, \
             patch('mechanical.opencode_connection.time.sleep'):
            result = self.api.wait_shell({'id': 'known', 'status': 'running'}, 20)
        self.assertEqual(result['status'], 'exited')
        self.assertEqual([c.args[0] for c in read.call_args_list], ['known', 'known'])
        submit.assert_not_called()

    def test_recovery_refuses_different_server_and_quotes_windows_paths(self):
        with self.assertRaisesRegex(ValueError, "different OpenCode server"):
            OpenCodeConnection(r"C:\worker", r"C:\python.exe", self.config, expected_url="https://another-server")
        connection = OpenCodeConnection(r"C:\O'Brien\worker", r"C:\Program Files\Python\python.exe", self.config)
        command = connection.command("check")
        script = base64.b64decode(command.split("-EncodedCommand ")[1]).decode("utf-16le")
        self.assertIn("'C:\\O''Brien\\worker\\scripts\\api-worker.py'", script)
        self.assertIn("'C:\\Program Files\\Python\\python.exe'", script)


if __name__ == "__main__":
    unittest.main()
