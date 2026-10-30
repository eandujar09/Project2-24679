"""Prepare a validated snapshot and run Mechanical in a separate interpreter."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import uuid

from mechanical.contract import validate_request, write_json
from .geometry import mechanical_signatures
from .viewer import ROOT


def default_python():
    """The Mechanical interpreter is user input, never a machine-specific guess."""
    return os.environ.get("MECHANICAL_PYTHON", "")


def prepare_request(workspace, model_id, element_size_mm=3.0):
    snapshot = workspace.project_snapshot(model_id)
    step = workspace.root / "models" / f"{model_id}.step"
    if hashlib.sha256(step.read_bytes()).hexdigest() != model_id:
        raise ValueError("The saved STEP file no longer matches its model hash.")
    signatures = mechanical_signatures(step)
    # Verify the signature traversal is the same identity used by the annotation UI.
    old = {face["key"]: face for face in snapshot["faces"]}
    if set(old) != {face["key"] for face in signatures}:
        raise ValueError("The CAD importer changed the stored face mapping. Reimport and reannotate the model.")
    for face in signatures:
        previous = old[face["key"]]
        if (abs(previous["areaMm2"] - face["areaMm2"]) > max(1e-7, face["areaMm2"] * 1e-8) or
                any(abs(a - b) > 1e-7 for a, b in zip(previous["centroidMm"], face["centroidMm"]))):
            raise ValueError("Stored face identity disagrees with the current CAD importer.")
    request = {"schemaVersion": 1, "modelId": model_id, "stepFile": str(step),
               "faceMapping": snapshot["faceMapping"], "units": snapshot["units"],
               "faceSignatures": signatures, "boundaryConditions": snapshot["boundaryConditions"],
               "comments": snapshot["comments"],
               "settings": {"mechanicalVersion": 261, "material": "Structural Steel", "elementSizeMm": element_size_mm,
                            "solverCores": 1, "largeDeflection": False}}
    validate_request(request)
    return request


def run_project(workspace, model_id, python_executable, element_size_mm=3.0, timeout_seconds=900):
    executable = Path(python_executable).expanduser().resolve()
    if not executable.is_file():
        raise ValueError("Choose an existing Python executable with ansys-mechanical-core installed.")
    request = prepare_request(workspace, model_id, element_size_mm)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = workspace.root / "exports" / "simulations" / f"{stamp}-{uuid.uuid4().hex[:10]}"
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "request.json", request)
    output = directory / "results"
    command = [str(executable), "-m", "mechanical.run", "--request", str(directory / "request.json"), "--output-dir", str(output)]
    timed_out = False
    with (directory / "run.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=os.name != "nt",
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
        try:
            code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            code = -1
    report_path = output / "report.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    else:
        report = {"status": "failed", "modelId": model_id,
                  "error": "Mechanical timed out." if timed_out else "Mechanical worker failed to start or exited before writing a report. See run.log."}
    if code != 0:
        report["status"] = "failed"
        if timed_out:
            report["error"] = "Mechanical timed out after {} seconds; this worker's process tree was stopped.".format(timeout_seconds)
        elif "error" not in report:
            report["error"] = "Mechanical worker exited with code {}; see run.log.".format(code)
    report["workerExitCode"] = code
    report["runDirectory"] = str(directory)
    write_json(directory / "report.json", report)
    archive = shutil.make_archive(str(directory / "simulation"), "zip", root_dir=directory, base_dir="results") if output.exists() else None
    # Include logs and the validated input alongside any Mechanical artifacts.
    if archive:
        import zipfile
        with zipfile.ZipFile(archive, "a", compression=zipfile.ZIP_DEFLATED) as bundle:
            for name in ("request.json", "report.json", "run.log"):
                bundle.write(directory / name, name)
    return {"report": report, "directory": directory, "archive": archive,
            "images": [str(output / f"{name}.png") for name in ("totalDeformation", "vonMisesStress")
                       if report["status"] == "succeeded" and (output / f"{name}.png").is_file()]}
