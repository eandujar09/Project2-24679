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
from .simulation import prepare_request, prepare_code_request, prepare_fluent_request


class RemoteSubmissionError(ValueError):
    submission_state = 'unknown'

    def __init__(self, message, record_path):
        super().__init__(message)
        self.record_path = str(record_path)


class PreSubmissionError(ValueError):
    """Positive evidence that the simulation transport was never invoked."""
    submission_state = 'not_submitted'


LEGACY_FLUENT_PREFLIGHT_ERRORS = frozenset({
    'Deploy the Fluent worker and install requirements-fluent.txt in the configured remote Python. A licensed Fluent 261 launch is still required.',
    'Deploy the Fluent worker and install requirements-fluent.txt in the configured remote Python. The configured worker is missing the required PyFluent version or protocol.',
})


def definite_non_submission(attempt):
    if attempt.get('submissionState') == 'not_submitted':
        return True
    # Narrow migration for the known old capability-check failure. Absence of a
    # job record alone is NOT evidence that an arbitrary execution never started.
    return (attempt.get('solver') == 'fluent' and attempt.get('status') == 'failed'
            and not any(attempt.get(k) for k in ('recordPath','recoverable','report','result','jobId'))
            and attempt.get('error') in LEGACY_FLUENT_PREFLIGHT_ERRORS)


def remote_host():
    if os.environ.get("MECHANICAL_TRANSPORT", "opencode") == "opencode":
        try:
            return OpenCodeAPI().url
        except ValueError:
            return "OpenCode (login not configured)"
    return os.environ.get("MECHANICAL_SSH_HOST", "")


def configured_connection(solver='mechanical'):
    transport = os.environ.get("MECHANICAL_TRANSPORT", "opencode")
    if transport == "opencode":
        if solver == 'fluent':
            return OpenCodeConnection(os.environ.get('FLUENT_REMOTE_DIR') or os.environ.get('MECHANICAL_REMOTE_DIR', ''),
                                      os.environ.get('FLUENT_REMOTE_PYTHON') or os.environ.get('MECHANICAL_REMOTE_PYTHON', ''))
        return OpenCodeConnection.from_environment()
    if transport != "ssh":
        raise ValueError("MECHANICAL_TRANSPORT must be opencode or ssh.")
    if solver == 'fluent':
        return SSHConnection(os.environ.get('MECHANICAL_SSH_HOST', ''),
                             os.environ.get('FLUENT_REMOTE_DIR') or os.environ.get('MECHANICAL_REMOTE_DIR', ''),
                             os.environ.get('FLUENT_REMOTE_PYTHON') or os.environ.get('MECHANICAL_REMOTE_PYTHON', ''),
                             os.environ.get('MECHANICAL_REMOTE_PLATFORM', 'windows'))
    return SSHConnection.from_environment()


def check_connection():
    connection = configured_connection()
    info = connection.check()
    if info.get("pyMechanicalVersion") != "0.12.7":
        raise ValueError("Connected, but install requirements-mechanical.txt in the configured remote Python environment.")
    method = "the OpenCode API" if getattr(connection, "transport", "ssh") == "opencode" else "SSH"
    return f"**Connected through {method}.** PyMechanical worker is available. This check verifies the connection and installed package, not a solver run."


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
    try:
        request = prepare_request(workspace, model_id, element_size_mm)
    except (ValueError,OSError) as exc:
        raise PreSubmissionError(str(exc)) from exc
    return submit_remote_request(workspace, request, progress, connection)


def run_remote_code(workspace, model_id, program, selected_face=None, connection=None):
    try:
        request = prepare_code_request(workspace, model_id, program, selected_face)
    except (ValueError,OSError) as exc:
        raise PreSubmissionError(str(exc)) from exc
    return submit_remote_request(workspace, request, connection=connection)


def run_remote_fluent_code(workspace, model_id, program, selected_face=None, connection=None):
    try:
        request = prepare_fluent_request(workspace, model_id, program, selected_face)
    except (ValueError,OSError) as exc:
        raise PreSubmissionError(str(exc)) from exc
    return submit_remote_request(workspace, request, connection=connection)


def fluent_worker_compatible(info):
    return str(info.get('pyFluentVersion','')).startswith('0.37.') and info.get('fluentWorkerProtocol') == 2


def check_fluent_worker(connection=None):
    connection=connection or configured_connection('fluent')
    info=connection.check()
    fields=('pyFluentVersion','fluentWorkerProtocol','requiredFluentVersion','licenseStatus')
    return {'compatible':fluent_worker_compatible(info),
            'worker':{key:info.get(key) for key in fields},
            'required':{'pyFluentVersion':'0.37.x','fluentWorkerProtocol':2,'fluentVersion':261},
            'solverLaunched':False,'licenseCheckPerformed':False,
            'scope':'Worker package/protocol compatibility only; no live Fluent API or solve verification.'}


def _prepare_submission(workspace, request, progress=None, connection=None):
    """Everything here happens before any simulation submission is attempted."""
    model_id = request['modelId']
    connection = connection or (configured_connection('fluent') if request.get('solver') == 'fluent' else configured_connection())
    info = connection.check()
    if request.get('solver') == 'fluent':
        if not fluent_worker_compatible(info):
            raise ValueError('Deploy the Fluent worker and install requirements-fluent.txt in the configured remote Python. The configured worker is missing the required PyFluent version or protocol.')
    elif info.get("pyMechanicalVersion") != "0.12.7":
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
    return connection,data,job_id,directory,expected,transport


def submit_remote_request(workspace, request, progress=None, connection=None):
    try:
        connection,data,job_id,directory,expected,transport = _prepare_submission(workspace,request,progress,connection)
    except Exception as exc:
        raise PreSubmissionError(str(exc)) from exc
    # From this point onward, failures may involve a real remote job. Never turn
    # them into a retryable preflight failure, including result-transfer errors.
    try:
        archive = (connection.run(data, directory / "remote-job.json") if transport == "opencode"
                   else receive_results(connection, "run", job_id, directory, data))
        report = extract_results(archive, directory, expected)
        return result_files(directory, report)
    except Exception as exc:
        if isinstance(exc,RemoteSubmissionError):
            raise
        raise RemoteSubmissionError(str(exc),directory/'remote-job.json') from exc


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
