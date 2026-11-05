"""Persistent project services; no Gradio or Mechanical dependency.

The Mechanical runner consumes project_snapshot(), imports the original STEP,
and explicitly resolves these CAD faces to Mechanical entities.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from threading import RLock
import uuid
from urllib.parse import quote

from . import geometry


def now():
    return datetime.now(timezone.utc).isoformat()


def nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text.")
    return value.strip()


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_annotations(data, model_id):
    if not isinstance(data, dict) or type(data.get("schemaVersion")) is not int or data["schemaVersion"] not in (1, 2):
        raise ValueError("Unsupported annotation schema; expected version 1 or 2.")
    if data.get("modelId") != model_id:
        raise ValueError("SHA-256 mismatch: open the exact original STEP file.")
    nonempty(data.get("filename"), "Filename")
    result = {}
    for collection in ("comments", "boundaryConditions"):
        records = [] if collection == "boundaryConditions" and data["schemaVersion"] == 1 else data.get(collection)
        if not isinstance(records, list) or (collection == "comments" and "comments" not in data):
            raise ValueError(f"Invalid {collection} array.")
        seen, validated = set(), []
        for item in records:
            if not isinstance(item, dict):
                raise ValueError("Annotation records must be objects.")
            record = {key: nonempty(item.get(key), key) for key in ("id", "faceKey", "createdAt", "updatedAt")}
            if record["id"] in seen or item.get("modelId") != model_id:
                raise ValueError("Duplicate annotation ID or incorrect model association.")
            seen.add(record["id"])
            record["modelId"] = model_id
            for key in ("createdAt", "updatedAt"):
                try:
                    datetime.fromisoformat(record[key].replace("Z", "+00:00"))
                except ValueError as exc:
                    raise ValueError("Invalid annotation timestamp.") from exc
            if collection == "comments":
                record["text"] = nonempty(item.get("text"), "Comment")
                if len(record["text"]) > 20000:
                    raise ValueError("Comments may contain at most 20,000 characters.")
                if "anchor" in item:
                    anchor = item["anchor"]
                    if not isinstance(anchor, list) or len(anchor) != 3 or not all(map(finite, anchor)):
                        raise ValueError("Invalid comment anchor.")
                    record["anchor"] = anchor
            else:
                kind, values = item.get("type"), item.get("values", {})
                if kind not in geometry.COLORS or not isinstance(values, dict):
                    raise ValueError("Invalid boundary-condition type or values.")
                if kind in ("force", "displacement"):
                    if not all(finite(values.get(axis)) for axis in "xyz"):
                        raise ValueError("X/Y/Z components must be finite numbers.")
                    values = {axis: values[axis] for axis in "xyz"}
                    if kind == "force" and not any(values.values()):
                        raise ValueError("Force must have a nonzero resultant.")
                elif kind == "pressure":
                    if not finite(values.get("magnitude")) or values["magnitude"] == 0:
                        raise ValueError("Pressure must be finite and nonzero.")
                    values = {"magnitude": values["magnitude"]}
                else:
                    values = {}
                record.update(type=kind, values=values)
            validated.append(record)
        result[collection] = validated
    return result


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        for name in ("models", "meshes", "previews", "exports"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, document TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "workspace.sqlite3", timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, model_id):
        with self.connect() as db:
            row = db.execute("SELECT document FROM projects WHERE id = ?", (model_id,)).fetchone()
        if row is None:
            raise ValueError("Open a STEP project first.")
        return json.loads(row[0])

    def _write(self, db, project):
        db.execute("INSERT OR REPLACE INTO projects VALUES (?, ?)",
                   (project["id"], json.dumps(project, allow_nan=False)))

    def projects(self):
        with self.connect() as db:
            projects = [json.loads(row[0]) for row in db.execute("SELECT document FROM projects ORDER BY rowid DESC")]
        return [(f'{p["filename"]} · {p["id"][:10]}', p["id"]) for p in projects]

    def open_step(self, filename):
        path = Path(filename)
        if path.suffix.lower() not in (".step", ".stp"):
            raise ValueError("Choose a .step or .stp file.")
        content = path.read_bytes()
        model_id = hashlib.sha256(content).hexdigest()
        with self.lock:
            try:
                return self.get(model_id)
            except ValueError:
                pass
            meshes, faces = geometry.read_step(path)
            (self.root / "models" / f"{model_id}.step").write_bytes(content)
            geometry.save_meshes(self.root / "meshes" / f"{model_id}.npz", meshes)
            project = {"id": model_id, "filename": path.name, "importedAt": now(),
                       "faceMapping": geometry.FACE_NAMESPACE, "faces": faces,
                       "comments": [], "boundaryConditions": []}
            with self.connect() as db:
                self._write(db, project)
        return project

    def require_face(self, project, face_key):
        if not isinstance(face_key, str) or face_key not in {face["key"] for face in project["faces"]}:
            raise ValueError("Select a mapped CAD face first.")

    def save_annotation(self, model_id, face_key, collection, payload, record_id=None):
        if collection not in ("comments", "boundaryConditions"):
            raise ValueError("Unknown annotation collection.")
        with self.lock, self.connect() as db:
            project = self.get(model_id)
            self.require_face(project, face_key)
            existing = next((r for r in project[collection] if r["id"] == record_id), None)
            if record_id and existing is None:
                raise ValueError("This annotation no longer exists; refresh the project.")
            if existing and existing["faceKey"] != face_key:
                raise ValueError("An edit cannot move an annotation to another face.")
            record = dict(payload, id=record_id or str(uuid.uuid4()), modelId=model_id,
                          faceKey=face_key, createdAt=existing["createdAt"] if existing else now(), updatedAt=now())
            envelope = {"schemaVersion": 2, "modelId": model_id, "filename": project["filename"],
                        "comments": [], "boundaryConditions": [], collection: [record]}
            record = validate_annotations(envelope, model_id)[collection][0]
            project[collection] = [r for r in project[collection] if r["id"] != record["id"]] + [record]
            self._write(db, project)
        return project

    def delete_annotation(self, model_id, collection, record_id, confirmed):
        if not confirmed:
            raise ValueError("Check the deletion confirmation box first.")
        if collection not in ("comments", "boundaryConditions") or not record_id:
            raise ValueError("Choose an annotation to delete.")
        with self.lock, self.connect() as db:
            project = self.get(model_id)
            project[collection] = [r for r in project[collection] if r["id"] != record_id]
            self._write(db, project)
        return project

    def import_annotations(self, model_id, path):
        incoming = validate_annotations(json.loads(Path(path).read_text(encoding="utf-8-sig")), model_id)
        with self.lock, self.connect() as db:
            project = self.get(model_id)
            for collection, records in incoming.items():
                merged = {r["id"]: r for r in project[collection]}
                merged.update({r["id"]: r for r in records})
                project[collection] = list(merged.values())
            self._write(db, project)
        return project

    def project_snapshot(self, model_id):
        """Solver-neutral mm/N/MPa data; face keys are NOT Mechanical IDs."""
        project = self.get(model_id)
        return {"schemaVersion": 2, "modelId": model_id, "filename": project["filename"],
                "faceMapping": project["faceMapping"], "units": {"length": "mm", "force": "N", "pressure": "MPa"},
                "faces": project["faces"], "comments": project["comments"],
                "boundaryConditions": project["boundaryConditions"]}

    def export_annotations(self, model_id):
        path = self.root / "exports" / f"{uuid.uuid4().hex}.json"
        path.write_text(json.dumps(self.project_snapshot(model_id), indent=2, allow_nan=False), encoding="utf-8")
        return str(path)

    def preview(self, model_id, selected=None):
        project = self.get(model_id)
        if selected:
            self.require_face(project, selected)
        return geometry.preview(self.root / "meshes" / f"{model_id}.npz", project["faces"],
                                project["boundaryConditions"], selected,
                                self.root / "previews" / f"{uuid.uuid4().hex}.glb")

    def viewer_state(self, model_id, selected=None, focus=False, highlighted=None, focus_face=None, **extra):
        project = self.get(model_id)
        if selected:
            self.require_face(project, selected)
        for key in highlighted or []:
            self.require_face(project, key)
        path = self.root / "previews" / f"{model_id}-viewer.json"
        with self.lock:
            if not path.exists():
                geometry.viewer_geometry(self.root / "meshes" / f"{model_id}.npz", project["faces"], path)
        return json.dumps({
            "modelId": model_id, "geometryUrl": f"/gradio_api/file={quote(path.as_posix(), safe='/:')}",
            "selected": selected, "focus": focus, "boundaryConditions": project["boundaryConditions"],
            "highlighted": highlighted or [], "focusFace": focus_face, **extra,
        }, allow_nan=False)
