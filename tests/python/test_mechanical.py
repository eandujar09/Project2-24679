import copy
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

from mechanical.contract import FaceMappingError, boundary_union_errors, match_faces, normalize_conditions, validate_request
from mechanical.prepare import prepare
from gradio_app.backend import Workspace
from gradio_app.simulation import default_python, prepare_request, run_project
from test_workspace import write_step, temporary_directory
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox


def record(key, kind, values, record_id="record"):
    return {"id": record_id, "faceKey": key, "type": kind, "values": values}


class ConditionContractTests(unittest.TestCase):
    def test_mechanical_interpreter_is_explicit_user_input(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(default_python(), "")
        with patch.dict("os.environ", {"MECHANICAL_PYTHON": "custom-environment/python"}, clear=True):
            self.assertEqual(default_python(), "custom-environment/python")

    def test_boundary_union_accepts_subdivision_but_not_missing_or_extra_trim(self):
        corners = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]
        divided = [corners[0], [0.5, 0, 0], *corners[1:]]
        source = {"key": "split", "areaMm2": 1, "centroidMm": [0.5, 0.5, 0],
                  "samples": [{"pointMm": [u, v, 0], "normal": [0, 0, 1]} for u, v in [(0.2, 0.2), (0.5, 0.5), (0.8, 0.8)]],
                  "verticesMm": divided, "edges": []}
        for a, b in zip(divided, divided[1:] + divided[:1]):
            source["edges"].append({"pointsMm": [a, b], "polylineMm": [a, b], "polylineDeflectionMm": 1e-6})
        candidate = {"id": 1, "areaMm2": 1, "centroidMm": [0.5, 0.5, 0], "verticesMm": corners,
                     "edgeIds": [0, 1, 2, 3],
                     "boundarySamplesMm": [p for a, b in zip(corners, corners[1:] + corners[:1])
                                           for p in (a, [(x+y)/2 for x, y in zip(a, b)], b)]}

        def project(edge_id, point):
            a, b = corners[edge_id], corners[(edge_id + 1) % 4]
            delta = [y-x for x, y in zip(a, b)]
            t = max(0, min(1, sum((p-x)*d for p, x, d in zip(point, a, delta))))
            return [x+t*d for x, d in zip(a, delta)]

        evaluate = lambda _, point: (point, [0, 0, 1])
        mapping, evidence = match_faces([source], [candidate], evaluate, evaluate_edge=project)
        self.assertEqual(mapping, {"split": 1})
        self.assertEqual(evidence[0]["trimMatchingMethod"], "bidirectional boundary union")
        # Thin faces can have very inaccurate faceted areas. They still need
        # the complete independent boundary test and unchanged normal check.
        mapping, _ = match_faces([source], [dict(candidate, areaMm2=1.07)], evaluate, evaluate_edge=project)
        self.assertEqual(mapping, {"split": 1})
        with self.assertRaises(FaceMappingError):
            match_faces([source], [candidate], lambda _, point: (point, [0, 0, -1]), evaluate_edge=project)
        # Reverse coverage is essential: projecting only source points would
        # miss a new hole boundary or an extra target extension.
        extra = dict(candidate, boundarySamplesMm=candidate["boundarySamplesMm"] + [[0.5, 0.5, 0]])
        with self.assertRaises(FaceMappingError):
            match_faces([source], [extra], evaluate, evaluate_edge=project)
        missing = copy.deepcopy(source)
        missing["edges"].pop()
        self.assertGreater(boundary_union_errors(missing, candidate, project, 1e-4)["reverseBoundaryErrorBoundMm"], 0.1)
        with self.assertRaises(FaceMappingError):
            match_faces([source], [dict(candidate, edgeIds=[0, 1, 2])], evaluate, evaluate_edge=project)
        incomplete = copy.deepcopy(source)
        del incomplete["edges"][0]["polylineMm"]
        with self.assertRaises(FaceMappingError):
            match_faces([incomplete], [candidate], evaluate, evaluate_edge=project)

    def test_stable_aggregation_and_pressure_sign(self):
        records = [record("support", "fixed", {}, "s"), record("load", "force", {"x": 3, "y": 0, "z": 1}, "b"),
                   record("load", "force", {"x": -1, "y": 2, "z": 0}, "a"), record("load", "pressure", {"magnitude": -4}, "p")]
        applied = normalize_conditions(records, {"support", "load"})
        self.assertEqual(applied, normalize_conditions(records[::-1], {"support", "load"}))
        self.assertEqual(applied[0]["values"], {"x": 2, "y": 2, "z": 1})
        self.assertEqual(applied[0]["sourceIds"], ["a", "b"])
        self.assertEqual(applied[1]["values"], {"magnitude": -4})

    def test_rejects_unsupported_conflicting_and_unloaded_setups(self):
        support = record("base", "fixed", {}, "s")
        force = record("tip", "force", {"x": 0, "y": 0, "z": 1}, "f")
        for records in ([], [force], [support], [support, record("missing", "force", force["values"], "g")],
                        [support, record("base", "force", force["values"], "g")],
                        [support, record("base", "displacement", {"x": 0, "y": 0, "z": 0}, "d"), force],
                        [support, force, force], [support, record("tip", "pressure", {"magnitude": float("nan")}, "p")]):
            with self.assertRaises(ValueError):
                normalize_conditions(records, {"base", "tip"})

    def test_one_to_one_face_matching_ignores_ids_and_refuses_ambiguity(self):
        signature = {"key": "face", "areaMm2": 10, "centroidMm": [1, 2, 3],
                     "samples": [{"pointMm": [1, 2, 3], "normal": [0, 0, 1]}] * 3}
        candidate = {"id": 9823, "areaMm2": 10, "centroidMm": [1, 2, 3]}
        evaluate = lambda face_id, point: (point, [0, 0, 1])
        mapping, evidence = match_faces([signature], [candidate], evaluate)
        self.assertEqual(mapping, {"face": 9823})
        self.assertEqual(evidence[0]["maxSurfaceErrorMm"], 0)
        with self.assertRaisesRegex(ValueError, "2 valid"):
            match_faces([signature, dict(signature, key="other")], [candidate, dict(candidate, id=9)], evaluate)
        with self.assertRaises(ValueError):
            match_faces([signature], [candidate], lambda face_id, point: (point, [0, 0, -1]))
        with self.assertRaises(ValueError):
            match_faces([signature], [candidate], lambda face_id, point: ([1, 2, 4], [0, 0, 1]))
        with self.assertRaises(ValueError):
            match_faces([signature], [], evaluate)

    def test_faceted_mass_properties_need_exact_trim_verification(self):
        vertices = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]
        source = {"key": "curved-import-regression", "areaMm2": 1, "centroidMm": [0.5, 0.5, 0],
                  "samples": [{"pointMm": [u, v, 0], "normal": [0, 0, 1]} for u, v in [(0.2, 0.2), (0.5, 0.5), (0.8, 0.8)]],
                  "verticesMm": vertices,
                  "edges": [{"pointsMm": [vertices[i], vertices[(i + 1) % 4]]} for i in range(4)]}
        candidate = {"id": 45, "areaMm2": 1.0064, "centroidMm": [0.537, 0.5, 0],
                     "verticesMm": vertices, "edgeIds": [10, 11, 12, 13]}

        def evaluate_edge(edge_id, point):
            a, b = vertices[edge_id - 10], vertices[(edge_id - 10 + 1) % 4]
            direction = [y - x for x, y in zip(a, b)]
            fraction = max(0, min(1, sum((p - x) * d for p, x, d in zip(point, a, direction))))
            return [x + fraction * d for x, d in zip(a, direction)]

        evaluate = lambda face_id, point: (point, [0, 0, 1])
        # No relaxation is permitted without the independent exact trim checks.
        with self.assertRaises(FaceMappingError):
            match_faces([source], [candidate], evaluate)
        mapping, evidence = match_faces([source], [candidate], evaluate, evaluate_edge=evaluate_edge)
        self.assertEqual(mapping, {source["key"]: 45})
        self.assertEqual(evidence[0]["trimEdgesVerified"], 4)
        shifted = dict(candidate, verticesMm=[[x + 0.02, y, z] for x, y, z in vertices])
        with self.assertRaises(FaceMappingError) as error:
            match_faces([source], [shifted], evaluate, evaluate_edge=evaluate_edge)
        self.assertEqual(error.exception.diagnostics["rejectedCandidates"][0]["rejectedBy"], "exact trim vertices")
        with self.assertRaises(FaceMappingError):
            match_faces([source], [candidate], evaluate, evaluate_edge=lambda edge_id, point: [p + 0.01 for p in point])


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = temporary_directory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.step = self.root / "box.step"
        write_step(self.step, BRepPrimAPI_MakeBox(10, 20, 30).Shape())
        self.workspace = Workspace(self.root / "workspace")
        self.project = self.workspace.open_step(self.step)
        self.mid = self.project["id"]
        self.workspace.save_annotation(self.mid, self.project["faces"][0]["key"], "boundaryConditions", {"type": "fixed", "values": {}})
        self.workspace.save_annotation(self.mid, self.project["faces"][1]["key"], "boundaryConditions", {"type": "force", "values": {"x": 10, "y": 0, "z": 0}})

    def test_prepare_from_workspace_and_portable_annotations(self):
        request = prepare_request(self.workspace, self.mid, 3)
        self.assertEqual(request["modelId"], hashlib.sha256(self.step.read_bytes()).hexdigest())
        self.assertEqual(len(request["faceSignatures"]), 6)
        self.assertTrue(all(len(face["samples"]) >= 3 for face in request["faceSignatures"]))
        self.assertEqual(len(validate_request(request)), 2)
        cli = prepare(self.step, self.workspace.export_annotations(self.mid), 3)
        self.assertEqual(cli["faceSignatures"], request["faceSignatures"])
        self.assertEqual(cli["boundaryConditions"], request["boundaryConditions"])

    def test_request_rejects_hash_units_material_and_size_changes(self):
        request = prepare_request(self.workspace, self.mid)
        for key, value in (("modelId", "not-the-file"), ("units", {"length": "m"}), ("faceMapping", "browser")):
            with self.assertRaises(ValueError):
                validate_request(dict(request, **{key: value}))
        for key, value in (("material", "unknown"), ("elementSizeMm", 0), ("elementSizeMm", float("inf")),
                           ("solverCores", 4), ("largeDeflection", True)):
            changed = copy.deepcopy(request)
            changed["settings"][key] = value
            with self.assertRaises(ValueError):
                validate_request(changed)

    def test_fresh_setup_keeps_exact_cad_identity_for_both_solver_paths(self):
        from gradio_app.simulation import prepare_code_request
        from mechanical.transfer import pack_submission, unpack_submission
        fresh = self.workspace.open_step(self.step, fresh=True)
        mid = fresh['id']
        self.workspace.import_annotations(mid, self.workspace.export_annotations(self.mid))
        request = prepare_request(self.workspace, mid)
        code_request = prepare_code_request(self.workspace, mid, {
            'title': 'Inspect CAD', 'objective': 'Inspect the fresh setup', 'code': 'print(ctx.geometry)'})
        for candidate in (request, code_request):
            self.assertEqual(candidate['modelId'], self.mid)
            self.assertNotEqual(candidate['modelId'], mid)
            self.assertEqual(len(validate_request(candidate)), 2)
            destination = self.root / ('transfer-' + str(candidate['schemaVersion']))
            destination.mkdir()
            restored = unpack_submission(pack_submission(candidate), destination)
            self.assertEqual(restored['boundaryConditions'], candidate['boundaryConditions'])
        cli = prepare(self.step, self.workspace.export_annotations(mid), 3)
        self.assertEqual(cli['boundaryConditions'], request['boundaryConditions'])
        # Identity checks still reject altered CAD, even though setup IDs are independent.
        (self.workspace.root / 'models' / (mid + '.step')).write_bytes(b'changed STEP')
        with self.assertRaisesRegex(ValueError, 'model hash'):
            prepare_request(self.workspace, mid)
        with self.assertRaisesRegex(ValueError, 'model hash'):
            prepare_code_request(self.workspace, mid, code_request['program'])

    def test_changed_stored_face_metadata_is_not_silently_remapped(self):
        project = self.workspace.get(self.mid)
        project["faces"][0]["centroidMm"][0] += 1
        with self.workspace.connect() as db:
            self.workspace._write(db, project)
        with self.assertRaisesRegex(ValueError, "identity disagrees"):
            prepare_request(self.workspace, self.mid)

    def test_worker_failure_retains_log_and_no_stale_contours(self):
        class FailedProcess:
            def __init__(self, command, **kwargs):
                kwargs["stdout"].write("No Mechanical license available\n")

            def wait(self, **kwargs):
                return 1

        import sys
        with patch("mechanical.execution.subprocess.Popen", FailedProcess):
            result = run_project(self.workspace, self.mid, sys.executable)
        self.assertEqual(result["report"]["status"], "failed")
        self.assertEqual(result["images"], [])
        self.assertIn("license", (result["directory"] / "run.log").read_text())
        self.assertTrue((result["directory"] / "report.json").is_file())


if __name__ == "__main__":
    unittest.main()
