"""Run one fixed simulation job via an API shell or an optional SSH command."""
import argparse
import base64
from contextlib import contextmanager
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import sys

from .contract import write_json
from .execution import execute_request, archive_run
from .transfer import MAX_INPUT, unpack_submission

ROOT = Path(__file__).resolve().parent.parent


@contextmanager
def worker_lock(root):
    """OS releases this lock on exit, including a crash; only one solver at a time."""
    path = root / "worker.lock"
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError("Another simulation is already running on this worker.") from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError("Another simulation is already running on this worker.") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def run_job(data, root, job_id, runner=execute_request):
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise ValueError("Invalid job ID.")
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with worker_lock(root):
        directory = root / job_id
        directory.mkdir()  # Never overwrite or rerun an existing job ID.
        request = unpack_submission(data, directory)
        metadata = {"jobId": job_id, "modelId": request["modelId"], "submissionSHA256": hashlib.sha256(data).hexdigest()}
        write_json(directory / "request.json", request)
        write_json(directory / "status.json", dict(metadata, status="running"))
        try:
            report = runner(request, directory, sys.executable, 900)
        except Exception as exc:
            report = {"status": "failed", "error": str(exc)}
            with (directory / "run.log").open("a", encoding="utf-8") as log:
                log.write("Worker failure: " + str(exc) + "\n")
        report.update(metadata)
        write_json(directory / "report.json", report)
        archive = archive_run(directory)
        write_json(directory / "status.json", report)
        return Path(archive)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "run", "run-file", "status", "fetch"))
    parser.add_argument("--job-id")
    parser.add_argument("--input-file")
    parser.add_argument("--data-dir", default=str(ROOT / "worker-data"))
    args = parser.parse_args()
    if args.action == "check":
        try:
            version = importlib.metadata.version("ansys-mechanical-core")
        except importlib.metadata.PackageNotFoundError:
            version = None
        print(json.dumps({"service": "project2-mechanical-ssh", "protocolVersion": 1,
                          "python": sys.executable, "platform": sys.platform,
                          "pyMechanicalVersion": version, "requiredMechanicalVersion": 261,
                          "licenseVerified": False}))
        return 0
    if not args.job_id or not re.fullmatch(r"[0-9a-f]{32}", args.job_id):
        parser.error("A valid --job-id is required.")
    root = Path(args.data_dir).resolve()
    if args.action == "run-file":
        if not args.input_file:
            parser.error("--input-file is required for run-file.")
        with Path(args.input_file).open("rb") as source:
            data = source.read(MAX_INPUT + 1)
        if len(data) > MAX_INPUT:
            raise ValueError("Job exceeds the 128 MiB upload limit.")
        archive = run_job(data, root, args.job_id)
        print((archive.parent / "status.json").read_text(encoding="utf-8"))
        return 0
    elif args.action == "run":
        wire = sys.stdin.buffer.read((MAX_INPUT * 4 // 3) + 8)
        if len(wire) > (MAX_INPUT * 4 // 3) + 4:
            raise ValueError("Job exceeds the 128 MiB upload limit.")
        data = base64.b64decode(wire.strip(), validate=True)
        if len(data) > MAX_INPUT:
            raise ValueError("Job exceeds the 128 MiB upload limit.")
        archive = run_job(data, root, args.job_id)
    elif args.action == "status":
        print((root / args.job_id / "status.json").read_text(encoding="utf-8"))
        return 0
    else:
        archive = root / args.job_id / "simulation.zip"
    with archive.open("rb") as source:
        # ASCII survives Windows PowerShell's native-output text handling.
        base64.encode(source, sys.stdout.buffer)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
