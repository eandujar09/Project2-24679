"""Run a Mechanical job in a separate, time-limited process."""

import json
import os
from pathlib import Path
import signal
import subprocess
import zipfile

from .contract import validate_request, write_json

ROOT = Path(__file__).resolve().parent.parent


def execute_request(request, directory, python_executable, timeout_seconds=900):
    directory = Path(directory).resolve()
    executable = Path(python_executable).expanduser().resolve()
    if not executable.is_file():
        raise ValueError("Choose an existing Python executable with ansys-mechanical-core installed.")
    validate_request(request)
    write_json(directory / "request.json", request)
    output = directory / "results"
    solver = 'Fluent' if request.get('solver') == 'fluent' else 'Mechanical'
    module = ('fluent.agent_run' if request.get('schemaVersion') == 3 else
              'mechanical.agent_run' if request.get('schemaVersion') == 2 else 'mechanical.run')
    command = [str(executable), "-m", module, "--request", str(directory / "request.json"),
               "--output-dir", str(output)]
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
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {
        "status": "failed", "modelId": request["modelId"],
        "error": f"{solver} worker did not produce a report. See run.log."}
    if code != 0:
        report["status"] = "failed"
        if timed_out:
            report["error"] = f"{solver} timed out after {timeout_seconds} seconds; its worker was stopped."
        else:
            report.setdefault("error", f"{solver} worker exited with code {code}; see run.log.")
    report.update(workerExitCode=code, runDirectory=str(directory))
    write_json(directory / "report.json", report)
    return report


def archive_run(directory):
    """Retain errors and logs even when Mechanical could not start."""
    directory = Path(directory)
    archive = directory / "simulation.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in ("request.json", "report.json", "run.log"):
            path = directory / name
            if path.is_file():
                bundle.write(path, name)
        output = directory / "results"
        if output.exists():
            for path in sorted(output.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    bundle.write(path, path.relative_to(directory).as_posix())
    return str(archive)


def result_files(directory, report):
    directory = Path(directory)
    native = directory / 'results' / 'setup.mechdat'
    native_files = ({'mechanicalFile': str(native)} if report.get('status') == 'succeeded'
                    and native.is_file() and native.stat().st_size else {})
    archive = directory / 'results' / 'simulation.mechpz'
    if (report.get('status') == 'succeeded' and report.get('nativeArchive', {}).get('includesResults')
            and archive.is_file() and archive.stat().st_size):
        native_files['mechanicalArchive'] = str(archive)
    if report.get("kind") == "generated-python":
        images = []
        for item in report.get("images", []):
            filename = item.get("file", "")
            if Path(filename).name == filename and filename.endswith(".png"):
                path = directory / "results" / filename
                if path.is_file():
                    images.append(str(path))
        return {**native_files, "report": report, "directory": directory, "archive": str(directory / "simulation.zip"),
                "images": images, "codeFile": str(directory / "results" / "agent.py")}
    return {**native_files, "report": report, "directory": directory, "archive": str(directory / "simulation.zip"),
            "images": [str(directory / "results" / f"{name}.png")
                       for name in ("totalDeformation", "vonMisesStress")
                       if report["status"] == "succeeded" and (directory / "results" / f"{name}.png").is_file()]}
