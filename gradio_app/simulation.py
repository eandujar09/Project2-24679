"""Prepare a validated snapshot and run Mechanical in a separate interpreter."""

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import uuid

from mechanical.contract import validate_request
from mechanical.execution import execute_request, archive_run, result_files
from .geometry import mechanical_signatures


def default_python():
    """The Mechanical interpreter is user input, never a machine-specific guess."""
    return os.environ.get("MECHANICAL_PYTHON", "")


def prepare_request(workspace, model_id, element_size_mm=3.0):
    snapshot = workspace.solver_snapshot(model_id)
    step = workspace.root / "models" / f"{model_id}.step"
    if hashlib.sha256(step.read_bytes()).hexdigest() != snapshot["modelId"]:
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
    request = {"schemaVersion": 1, "modelId": snapshot["modelId"], "stepFile": str(step),
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
    report = execute_request(request, directory, executable, timeout_seconds)
    archive_run(directory)
    return result_files(directory, report)


def prepare_code_request(workspace, model_id, program, selected_face=None):
    from mechanical.program import validate_program
    snapshot = workspace.solver_snapshot(model_id)
    step = workspace.root / "models" / f"{model_id}.step"
    if hashlib.sha256(step.read_bytes()).hexdigest() != snapshot["modelId"]:
        raise ValueError("The saved STEP file no longer matches its model hash.")
    program = dict(program, sha256=validate_program(program))
    warning = None
    try:
        signatures = mechanical_signatures(step, require_single_solid=False)
        if {f['key'] for f in signatures} != {f['key'] for f in snapshot['faces']}:
            raise ValueError('The current importer changed the original face identities.')
    except ValueError as exc:
        signatures = []
        warning = str(exc)
    request = {"schemaVersion": 2, "modelId": snapshot["modelId"], "stepFile": str(step),
               "faceMapping": snapshot['faceMapping'], "units": snapshot['units'],
               "faceSignatures": signatures, "faceMappingWarning": warning,
               "sourceFaces": snapshot['faces'], "selectedFace": selected_face,
               "boundaryConditions": snapshot['boundaryConditions'], "comments": snapshot['comments'],
               "program": program,
               "settings": {"mechanicalVersion": 261, "solverCores": 1, "maxMeshEntities": 32000}}
    validate_request(request)
    return request
