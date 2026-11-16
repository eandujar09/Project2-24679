"""Persistent project services; no Gradio or Mechanical dependency.

The Mechanical runner consumes solver_snapshot(), imports the original STEP,
and explicitly resolves these CAD faces to Mechanical entities.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import sys
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
                from fluent.contract import KINDS, condition_values
                from .thermal import KINDS as THERMAL_KINDS, condition_values as thermal_values
                if kind in KINDS:
                    values = condition_values(kind, values)
                elif kind in THERMAL_KINDS:
                    values = thermal_values(kind, values)
                elif kind in ("force", "displacement"):
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

    def set_fluent_analysis(self, model_id, analysis):
        from fluent.contract import validate_analysis
        analysis = validate_analysis(analysis)
        with self.lock, self.connect() as db:
            project = self.get(model_id)
            project['fluentAnalysis'] = analysis
            self._write(db, project)
        return project

    def set_simulation_intent(self, model_id, simulation_type, domain_status=None):
        if simulation_type not in ('mechanical', 'heat_transfer', 'fluid'):
            raise ValueError('Choose mechanical, heat transfer, or fluid dynamics.')
        if domain_status not in (None, 'existing', 'needs_added', 'unsure'):
            raise ValueError('Specify whether the fluid domain already exists, needs adding, or is uncertain.')
        if simulation_type != 'fluid' and domain_status is not None:
            raise ValueError('The domain question applies only to fluid simulations.')
        with self.lock, self.connect() as db:
            project = self.get(model_id)
            previous = project.get('simulationIntent') or {}
            if simulation_type == 'fluid' and domain_status is None and previous.get('type') == 'fluid':
                domain_status = previous.get('domainStatus')
            project['simulationIntent'] = {'type': simulation_type, 'domainStatus': domain_status}
            self._write(db, project)
        return project['simulationIntent']

    def set_fluid_domain(self, model_id, kind, cad_role, parameters, description):
        from .fluid_domain import validate_domain
        domain = validate_domain(kind, cad_role, parameters, description)
        with self.lock, self.connect() as db:
            project = self.get(model_id)
            project['fluidDomain'] = domain
            project['simulationIntent'] = {'type':'fluid', 'domainStatus': 'existing' if kind == 'existing' else 'needs_added'}
            self._write(db, project)
        return domain

    def suggest_fluid_domain(self, model_id, clearance_mm=None, fixed_axes=()):
        project = self.get(model_id)
        bounds = [f['boundsMm'] for f in project['faces']]
        lower = [min(b[0][i] for b in bounds) for i in range(3)]
        upper = [max(b[1][i] for b in bounds) for i in range(3)]
        if clearance_mm is None:
            clearance_mm = max(1.0, max(b-a for a,b in zip(lower,upper)) * 0.02)
        if not finite(clearance_mm) or clearance_mm <= 0:
            raise ValueError('Clearance must be positive and finite (mm).')
        if any(a not in ('x','y','z') for a in fixed_axes):
            raise ValueError('Fixed axes must be x, y or z.')
        previous = project.get('fluidDomain') or {}
        if fixed_axes and previous.get('kind') != 'box':
            raise ValueError('Define the fixed box bounds first.')
        p = {}
        for i, axis in enumerate('xyz'):
            p['min_'+axis] = previous['parameters']['min_'+axis] if axis in fixed_axes else min(lower[i]-clearance_mm, previous.get('parameters',{}).get('min_'+axis, lower[i]))
            p['max_'+axis] = previous['parameters']['max_'+axis] if axis in fixed_axes else max(upper[i]+clearance_mm, previous.get('parameters',{}).get('max_'+axis, upper[i]))
        return {'kind':'box', 'cadRole':'obstacle', 'parameters':p, 'clearanceMm':clearance_mm,
                'fixedAxes':list(fixed_axes), 'requiresConfirmation':True,
                'note':'Proposed geometric gap only; not a CFD adequacy or convergence criterion.'}

    def create_fluid_domain(self, model_id, definition, timeout_seconds=120):
        """Bounded CAD subprocess; publish a derived project only after validation."""
        from .fluid_domain import validate_domain
        definition = validate_domain(definition['kind'],definition['cadRole'],definition['parameters'],definition['description'])
        project = self.get(model_id)
        if project.get('domainGeneration'):
            raise ValueError('Open the original obstacle model before constructing another enclosure.')
        source = self.root / 'models' / f'{model_id}.step'
        source_content = source.read_bytes()
        actual = hashlib.sha256(source_content).hexdigest()
        if actual != project.get('cadSha256',model_id):
            raise ValueError('Original CAD hash changed; refusing to build from different geometry.')
        fingerprint = hashlib.sha256(json.dumps({'source':actual,'definition':definition,'version':1},sort_keys=True).encode()).hexdigest()
        with self.lock, self.connect() as db:
            for row in db.execute('SELECT document FROM projects'):
                existing = json.loads(row[0])
                provenance = existing.get('domainGeneration') or {}
                if provenance.get('fingerprint') == fingerprint and provenance.get('sourceModelId') == model_id:
                    cached = self.root/'models'/f'{existing["id"]}.step'
                    if not cached.is_file() or hashlib.sha256(cached.read_bytes()).hexdigest() != existing['cadSha256']:
                        raise ValueError('The previously generated STEP is missing or changed. It was not overwritten or silently reused.')
                    return existing
        directory = self.root / 'exports' / 'domains' / uuid.uuid4().hex
        directory.mkdir(parents=True)
        source_snapshot = directory/'source.step'
        source_snapshot.write_bytes(source_content)
        output = directory / 'fluid-domain.step'
        request = {'source':str(source_snapshot),'definition':definition,'output':str(output),'report':str(directory/'geometry-report.json')}
        (directory/'request.json').write_text(json.dumps(request,allow_nan=False),encoding='utf-8')
        with (directory/'geometry.log').open('w',encoding='utf-8') as log:
            try:
                process = subprocess.run([sys.executable,'-m','gradio_app.domain_geometry','--request',str(directory/'request.json')],
                    cwd=Path(__file__).resolve().parents[1],stdout=log,stderr=subprocess.STDOUT,timeout=timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                raise ValueError('Fluid CAD construction exceeded the time limit. Original model retained; no derived geometry activated.') from exc
        report_path = directory/'geometry-report.json'
        if not report_path.is_file():
            raise ValueError('CAD worker returned no report. Original model retained; see domain geometry.log.')
        report = json.loads(report_path.read_text(encoding='utf-8'))
        if process.returncode or report.get('status') != 'succeeded':
            raise ValueError(report.get('error','Fluid CAD construction failed.'))
        if report.get('sourceSHA256') != actual:
            raise ValueError('CAD worker source identity does not match the approved geometry.')
        derived = self.open_step(output,fresh=True)
        derived['filename'] = Path(project['filename']).stem + '-fluid-domain.step'
        derived['simulationIntent'] = {'type':'fluid','domainStatus':'existing'}
        derived['fluidDomain'] = {'kind':'existing','cadRole':'fluid_volume','parameters':{},
                                  'description':'Verified derived '+definition['kind']+' fluid volume.','status':'ready'}
        derived['domainGeneration'] = dict(report,sourceModelId=model_id,definition=definition,
                                           fingerprint=fingerprint,artifactDirectory=str(directory))
        for face in derived['faces']:
            face['boundaryRole'] = report['faceRoles'][face['key']]
        # Conditions/comments intentionally start empty: face identities changed.
        with self.lock,self.connect() as db:
            self._write(db,derived)
        return derived

    def open_step(self, filename, *, fresh=False):
        """Import a separate setup when fresh; legacy callers may reopen by CAD hash."""
        path = Path(filename)
        if path.suffix.lower() not in (".step", ".stp"):
            raise ValueError("Choose a .step or .stp file.")
        content = path.read_bytes()
        cad_hash = hashlib.sha256(content).hexdigest()
        model_id = uuid.uuid4().hex if fresh else cad_hash
        with self.lock:
            if not fresh:
                try:
                    return self.get(model_id)
                except ValueError:
                    pass
            meshes, faces = geometry.read_step(path)
            (self.root / "models" / f"{model_id}.step").write_bytes(content)
            geometry.save_meshes(self.root / "meshes" / f"{model_id}.npz", meshes)
            project = {"id": model_id, "cadSha256": cad_hash, "filename": path.name, "importedAt": now(),
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
        with self.lock, self.connect() as db:
            project = self.get(model_id)
            cad_hash = project.get("cadSha256", model_id)
            incoming = validate_annotations(json.loads(Path(path).read_text(encoding="utf-8-sig")), cad_hash)
            for collection, records in incoming.items():
                merged = {r["id"]: r for r in project[collection]}
                merged.update({r["id"]: dict(r, modelId=model_id) for r in records})
                project[collection] = list(merged.values())
            self._write(db, project)
        return project

    def project_snapshot(self, model_id):
        """Solver-neutral mm/N/MPa data; face keys are NOT Mechanical IDs."""
        project = self.get(model_id)
        return {"schemaVersion": 2, "modelId": model_id, "cadSha256": project.get("cadSha256", model_id),
                "filename": project["filename"],
                "faceMapping": project["faceMapping"], "units": {"length": "mm", "force": "N", "pressure": "MPa"},
                "faces": project["faces"], "comments": project["comments"],
                "boundaryConditions": project["boundaryConditions"]}

    def solver_snapshot(self, model_id):
        """Keep portable annotations and worker identity bound to the exact STEP bytes."""
        snapshot = self.project_snapshot(model_id)
        snapshot["modelId"] = snapshot["cadSha256"]
        for collection in ("comments", "boundaryConditions"):
            snapshot[collection] = [dict(row, modelId=snapshot["modelId"]) for row in snapshot[collection]]
        return snapshot

    def export_annotations(self, model_id):
        path = self.root / "exports" / f"{uuid.uuid4().hex}.json"
        path.write_text(json.dumps(self.solver_snapshot(model_id), indent=2, allow_nan=False), encoding="utf-8")
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
