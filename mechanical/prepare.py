"""Prepare a deterministic job from exported annotations (use the Gradio venv).

python -m mechanical.prepare --step model.step --annotations notes.json --output request.json --element-size-mm 3
"""

import argparse
import hashlib
import json
from pathlib import Path

from gradio_app.backend import validate_annotations
from gradio_app.geometry import mechanical_signatures
from .contract import validate_request, write_json


def prepare(step, annotations, element_size_mm=3.0):
    step = Path(step).resolve()
    model_id = hashlib.sha256(step.read_bytes()).hexdigest()
    document = json.loads(Path(annotations).read_text(encoding="utf-8-sig"))
    incoming = validate_annotations(document, model_id)
    if document.get("faceMapping") != "python-ocp-v1":
        raise ValueError("Export annotations from the Python Gradio app; browser-importer face keys cannot be used for solving.")
    request = {"schemaVersion": 1, "modelId": model_id, "stepFile": str(step),
               "faceMapping": "python-ocp-v1", "units": {"length": "mm", "force": "N", "pressure": "MPa"},
               "faceSignatures": mechanical_signatures(step), **incoming,
               "settings": {"mechanicalVersion": 261, "material": "Structural Steel", "elementSizeMm": element_size_mm,
                            "solverCores": 1, "largeDeflection": False}}
    validate_request(request)
    return request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step", required=True)
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--element-size-mm", type=float, default=3)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists():
        raise ValueError("Refusing to overwrite an existing request file.")
    request = prepare(args.step, args.annotations, args.element_size_mm)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, request)
    print(output)


if __name__ == "__main__":
    main()
