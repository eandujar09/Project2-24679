"""Transport tests use synthetic solver output. They do not validate Ansys results."""
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid
import zipfile

from gradio_app.remote import run_remote_project
from gradio_app.simulation import prepare_request
from mechanical.contract import write_json
from mechanical.ssh_connection import SSHConnection
from mechanical.ssh_worker import run_job, worker_lock
from mechanical.transfer import extract_results, pack_submission
import test_mechanical

ROOT = Path(__file__).resolve().parents[2]


def fake_solve(request, directory, executable, timeout):
    output = directory / "results"
    output.mkdir()
    (directory / "run.log").write_text("Synthetic transport test. No Mechanical solve was performed.\n")
    (output / "totalDeformation.txt").write_text("synthetic transport fixture")
    report = {"status": "succeeded", "modelId": request["modelId"], "syntheticTest": True}
    write_json(directory / "report.json", report)
    return report


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_mechanical.RequestTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.workspace, self.mid = self.fixture.root, self.fixture.workspace, self.fixture.mid
        self.request = prepare_request(self.workspace, self.mid)

    def test_terminal_transport_round_trip_and_remote_path_remapping(self):
        worker_root = self.root / "remote-worker"
        fixture_script = self.root / "fixture_worker.py"
        fixture_script.write_text(
            f"import sys\nsys.path[:0] = {[str(ROOT), str(ROOT / 'tests/python')]!r}\n"
            "from mechanical import ssh_worker as worker\nfrom test_remote import fake_solve\n"
            "original = worker.run_job\n"
            "worker.run_job = lambda data, root, jid: original(data, root, jid, runner=fake_solve)\n"
            f"sys.argv += ['--data-dir', {str(worker_root)!r}]\nworker.main()\n")

        class LocalTerminal:
            host, directory, python, platform = "local-test", str(ROOT), sys.executable, "posix"
            def check(self):
                return {"pyMechanicalVersion": "0.12.7"}
            def command(self, action, job_id=None):
                return [sys.executable, str(fixture_script), action, "--job-id", job_id]

        result = run_remote_project(self.workspace, self.mid, connection=LocalTerminal())
        self.assertTrue(result["report"]["syntheticTest"])
        self.assertEqual(result["report"]["status"], "succeeded")
        self.assertEqual(result["report"]["modelId"], self.mid)
        self.assertTrue(Path(result["archive"]).is_file())
        self.assertEqual(result["images"], [])
        received = json.loads((result["directory"] / "request.json").read_text())
        self.assertIn(str(worker_root), received["stepFile"])
        self.assertNotEqual(received["stepFile"], self.request["stepFile"])

    def test_hash_mismatch_and_extra_paths_are_rejected_before_running(self):
        calls = []
        def forbidden(*args):
            calls.append(args)
            raise AssertionError("Invalid input must not reach Mechanical")
        bad_hash = pack_submission(dict(self.request, modelId="0"*64))
        malicious = io.BytesIO(pack_submission(self.request))
        with zipfile.ZipFile(malicious, "a") as bundle:
            bundle.writestr("../escape", "unsafe")
        for data in (bad_hash, malicious.getvalue()):
            with self.assertRaises(ValueError):
                run_job(data, self.root / "worker", uuid.uuid4().hex, runner=forbidden)
        self.assertEqual(calls, [])

    def test_failure_keeps_logs_and_job_cannot_run_twice(self):
        def fail(*args):
            raise RuntimeError("Simulated missing license")
        data, jid = pack_submission(self.request), uuid.uuid4().hex
        archive = run_job(data, self.root / "worker", jid, runner=fail)
        with zipfile.ZipFile(archive) as bundle:
            self.assertIn(b"missing license", bundle.read("run.log"))
            self.assertEqual(json.loads(bundle.read("report.json"))["status"], "failed")
        with self.assertRaises(FileExistsError):
            run_job(data, self.root / "worker", jid, runner=fake_solve)

    def test_busy_worker_rejects_a_second_process(self):
        self.root.mkdir(exist_ok=True)
        with worker_lock(self.root):
            with self.assertRaisesRegex(ValueError, "already running"):
                with worker_lock(self.root):
                    self.fail("A concurrent solver was allowed")

    def test_archive_identity_and_traversal_are_checked_before_extraction(self):
        expected = {"jobId": "a"*32, "modelId": self.mid, "submissionSHA256": "b"*64}
        destination = self.root / "download"
        destination.mkdir()
        for changed in ("identity", "traversal"):
            archive = self.root / f"{changed}.zip"
            report = dict(expected, status="succeeded")
            if changed == "identity":
                report["modelId"] = "c"*64
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("report.json", json.dumps(report))
                bundle.writestr("request.json", "{}")
                bundle.writestr("run.log", "test")
                if changed == "traversal":
                    bundle.writestr("results/../../escape", "unsafe")
            with self.assertRaises(ValueError):
                extract_results(archive, destination, expected)
            self.assertEqual(list(destination.iterdir()), [])

    def test_windows_command_quotes_paths_and_keeps_host_verification(self):
        connection = SSHConnection("user@100.88.230.43", "C:/Users/O'Brien/Worker", "C:/Program Files/Python/python.exe")
        command = connection.command("check")
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("BatchMode=yes", command)
        encoded = command[-1].split("-EncodedCommand ")[1]
        script = base64.b64decode(encoded).decode("utf-16le")
        self.assertIn("'C:/Users/O''Brien/Worker/scripts/ssh-worker.py'", script)
        self.assertIn("'C:/Program Files/Python/python.exe'", script)
        with self.assertRaises(ValueError):
            SSHConnection("-oProxyCommand=bad", "/tmp", "python", "posix")

    def test_disconnect_preserves_job_id_without_automatic_resubmission(self):
        connection = SSHConnection("test-host", "/tmp/worker", "python", "posix")
        with patch.object(SSHConnection, "check", return_value={"pyMechanicalVersion": "0.12.7"}), \
             patch("gradio_app.remote.subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", 1)) as run:
            with self.assertRaisesRegex(ValueError, "may still be running"):
                run_remote_project(self.workspace, self.mid, connection=connection)
        self.assertEqual(run.call_count, 1)
        records = list((self.workspace.root / "exports/simulations").glob("*/remote-job.json"))
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0].read_text())["modelId"], self.mid)


if __name__ == "__main__":
    unittest.main()
