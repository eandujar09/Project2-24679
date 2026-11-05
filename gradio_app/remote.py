"""Run the Mechanical worker through OpenCode's API or optional SSH over Tailscale."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

from mechanical.contract import write_json
from mechanical.execution import result_files
from mechanical.ssh_connection import SSHConnection
from mechanical.opencode_connection import OpenCodeAPI, OpenCodeConnection
from mechanical.transfer import MAX_RESULTS, extract_results, pack_submission
from .simulation import prepare_request, prepare_code_request


class RemoteSubmissionError(ValueError):
    def __init__(self, message, record_path):
        super().__init__(message)
        self.record_path = str(record_path)


def remote_host():
    if os.environ.get("MECHANICAL_TRANSPORT", "opencode") == "opencode":
        try:
            return OpenCodeAPI().url
        except ValueError:
            return "OpenCode (login not configured)"
    return os.environ.get("MECHANICAL_SSH_HOST", "")


def configured_connection():
    transport = os.environ.get("MECHANICAL_TRANSPORT", "opencode")
    if transport == "opencode":
        return OpenCodeConnection.from_environment()
    if transport != "ssh":
        raise ValueError("MECHANICAL_TRANSPORT must be opencode or ssh.")
    return SSHConnection.from_environment()


def check_connection():
    connection = configured_connection()
    info = connection.check()
    if info.get("pyMechanicalVersion") != "0.12.7":
        raise ValueError("Connected, but install requirements-mechanical.txt in the configured remote Python environment.")
    method = "the OpenCode API" if getattr(connection, "transport", "ssh") == "opencode" else "SSH"
    return f"**Connected through {method}.** PyMechanical is installed. A real simulation verifies Mechanical 261 and its license."


def receive_results(connection, action, job_id, directory, data=None, timeout_seconds=1050):
    encoded = directory / "download.b64"
    errors = directory / "ssh.log"
    try:
        with encoded.open("wb") as output, errors.open("wb") as stderr:
            result = subprocess.run(connection.command(action, job_id), input=base64.b64encode(data) if data is not None else None,
                                    stdout=output, stderr=stderr, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"Stopped waiting for remote job {job_id}; it may still be running. "
                         "Use scripts/remote-job.py to check or retrieve it before submitting again.") from exc
    if result.returncode:
        detail = errors.read_text(errors="replace")[-2000:]
        raise ValueError(f"SSH job {job_id} could not return results: {detail}. "
                         "The job record is saved locally; check it before retrying.")
    if encoded.stat().st_size > MAX_RESULTS * 4 // 3 + MAX_RESULTS // 50:
        raise ValueError("The remote result archive exceeds the transfer limit.")
    archive = directory / "simulation.zip"
    with encoded.open("rb") as source, archive.open("wb") as target:
        base64.decode(source, target)
    encoded.unlink()
    return archive


def run_remote_project(workspace, model_id, element_size_mm=3, progress=None, connection=None):
    request = prepare_request(workspace, model_id, element_size_mm)
    return submit_remote_request(workspace, request, progress, connection)


def run_remote_code(workspace, model_id, program, selected_face=None, connection=None):
    request = prepare_code_request(workspace, model_id, program, selected_face)
    return submit_remote_request(workspace, request, connection=connection)


def submit_remote_request(workspace, request, progress=None, connection=None):
    model_id = request['modelId']
    connection = connection or configured_connection()
    info = connection.check()
    if info.get("pyMechanicalVersion") != "0.12.7":
        raise ValueError("The remote Python environment needs requirements-mechanical.txt installed.")
    data = pack_submission(request)
    job_id = uuid.uuid4().hex
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = workspace.root / "exports" / "simulations" / f"{stamp}-{job_id[:10]}"
    directory.mkdir(parents=True)
    expected = {"jobId": job_id, "modelId": model_id, "submissionSHA256": hashlib.sha256(data).hexdigest()}
    write_json(directory / "local-request.json", request)
    if request.get("program"):
        (directory / "agent.py").write_text(request["program"]["code"], encoding="utf-8")
    transport = getattr(connection, "transport", "ssh")
    write_json(directory / "remote-job.json", dict(expected, transport=transport, remoteHost=connection.host,
               remoteDirectory=connection.directory, remotePython=connection.python, remotePlatform=connection.platform))
    if progress:
        progress(0.35, desc="Remote Ansys: importing, meshing, solving, and returning results")
    try:
        archive = (connection.run(data, directory / "remote-job.json") if transport == "opencode"
                   else receive_results(connection, "run", job_id, directory, data))
    except (ValueError, OSError) as exc:
        raise RemoteSubmissionError(str(exc), directory / 'remote-job.json') from exc
    report = extract_results(archive, directory, expected)
    return result_files(directory, report)


def recover_job(record_path, fetch=False):
    path = Path(record_path).resolve()
    record = json.loads(path.read_text())
    if record.get("transport") == "opencode":
        connection = OpenCodeConnection(record["remoteDirectory"], record["remotePython"], expected_url=record["remoteHost"])
        if not fetch:
            return connection.status(record)
        archive = connection.fetch(record["jobId"], path.parent)
        expected = {key: record[key] for key in ("jobId", "modelId", "submissionSHA256")}
        return extract_results(archive, path.parent, expected)
    connection = SSHConnection(record.get("remoteHost", record.get("sshHost")), record["remoteDirectory"], record["remotePython"], record["remotePlatform"])
    if not fetch:
        result = subprocess.run(connection.command("status", record["jobId"]), capture_output=True, timeout=25)
        if result.returncode:
            raise ValueError(result.stderr.decode(errors="replace"))
        return json.loads(result.stdout)
    archive = receive_results(connection, "fetch", record["jobId"], path.parent, timeout_seconds=180)
    expected = {key: record[key] for key in ("jobId", "modelId", "submissionSHA256")}
    return extract_results(archive, path.parent, expected)
