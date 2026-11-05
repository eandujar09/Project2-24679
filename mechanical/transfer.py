"""Portable job/result archives shared by the Mac app and the SSH worker."""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile

from .contract import validate_request

MAX_INPUT = 128 * 1024 * 1024
MAX_RESULTS = 2 * 1024 * 1024 * 1024


def pack_submission(request):
    step = Path(request["stepFile"])
    data = json.dumps(dict(request, stepFile="source.step"), allow_nan=False).encode()
    if step.stat().st_size + len(data) > MAX_INPUT:
        raise ValueError("The model and simulation settings exceed the 128 MiB transfer limit.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("request.json", data)
        bundle.write(step, "source.step")
    if buffer.tell() > MAX_INPUT:
        raise ValueError("The compressed job exceeds the 128 MiB transfer limit.")
    return buffer.getvalue()


def unpack_submission(data, directory):
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        files = bundle.infolist()
        if len(files) != 2 or {f.filename for f in files} != {"request.json", "source.step"}:
            raise ValueError("A job must contain only request.json and source.step.")
        if sum(f.file_size for f in files) > MAX_INPUT:
            raise ValueError("The expanded job exceeds 128 MiB.")
        request = json.loads(bundle.read("request.json"))
        step = bundle.read("source.step")
        if not isinstance(request, dict) or hashlib.sha256(step).hexdigest() != request.get("modelId"):
            raise ValueError("The STEP file does not match the submitted model hash.")
        path = directory / "source.step"
        path.write_bytes(step)
        request["stepFile"] = str(path)
        validate_request(request)
        return request


def extract_results(archive, directory, expected):
    with zipfile.ZipFile(archive) as bundle:
        files, seen = bundle.infolist(), set()
        if len(files) > 20000 or sum(f.file_size for f in files) > MAX_RESULTS:
            raise ValueError("The expanded result archive exceeds its limits.")
        for item in files:
            name, path = item.filename, PurePosixPath(item.filename)
            if (name in seen or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name
                    or stat.S_ISLNK(item.external_attr >> 16)
                    or (name not in ("request.json", "report.json", "run.log") and not name.startswith("results/"))):
                raise ValueError("The result archive contains an invalid path.")
            seen.add(name)
        if not {"request.json", "report.json", "run.log"}.issubset(seen):
            raise ValueError("The result archive is missing its input, report, or log.")
        report = json.loads(bundle.read("report.json"))
        if any(report.get(k) != v for k, v in expected.items()):
            raise ValueError("Results do not match the submitted model and job.")
        if report.get("status") not in ("succeeded", "failed"):
            raise ValueError("The simulation report is not complete.")
        for item in files:
            destination = directory / item.filename
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(item) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
        return report
