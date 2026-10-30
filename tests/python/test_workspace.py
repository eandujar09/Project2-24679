import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np
import trimesh
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.gp import gp_Trsf, gp_Vec

from gradio_app.backend import Workspace, validate_annotations
from gradio_app.geometry import read_step
from gradio_app.geometry import mechanical_signatures


TEMP_ROOT = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Temp" / "opencode"


def temporary_directory():
    return tempfile.TemporaryDirectory(dir=TEMP_ROOT if TEMP_ROOT.is_dir() else None)


def write_step(path, shape):
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    if writer.Write(str(path)) != IFSelect_RetDone:
        raise RuntimeError("Could not generate STEP fixture")


class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = temporary_directory()
        cls.root = Path(cls.temp.name)
        cls.box = cls.root / "box.step"
        cls.cylinder = cls.root / "cylinder.step"
        write_step(cls.box, BRepPrimAPI_MakeBox(10, 20, 30).Shape())
        write_step(cls.cylinder, BRepPrimAPI_MakeCylinder(5, 20).Shape())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.data = temporary_directory()
        self.addCleanup(self.data.cleanup)
        self.workspace = Workspace(self.data.name)
        self.project = self.workspace.open_step(self.box)
        self.mid = self.project["id"]
        self.key = self.project["faces"][0]["key"]

    def save_comment(self, text="A note"):
        return self.workspace.save_annotation(self.mid, self.key, "comments", {"text": text})

    def test_original_faces_and_mm_units(self):
        self.assertEqual(len(self.project["faces"]), 6)
        self.assertAlmostEqual(sum(f["areaMm2"] for f in self.project["faces"]), 2200)
        meshes, faces = read_step(self.cylinder)
        self.assertEqual(len(faces), 3)
        self.assertGreater(max(len(m.faces) for m in meshes), 10)
        self.assertEqual(len({f["key"] for f in faces}), 3)
        self.assertAlmostEqual(sum(f["areaMm2"] for f in faces), 250 * np.pi, places=5)
        signatures = mechanical_signatures(self.cylinder)
        # The cylindrical face has two circular trim edges; the arbitrary
        # periodic seam is not a real boundary and Mechanical omits it.
        cylindrical = next(face for face in signatures if face["surfaceType"] == "Cylinder")
        self.assertEqual(len(cylindrical["edges"]), 2)
        self.assertEqual(len(cylindrical["verticesMm"]), 2)

    def test_step_placement_applies_to_preview(self):
        transform = gp_Trsf()
        transform.SetTranslation(gp_Vec(100, 200, 300))
        shape = BRepBuilderAPI_Transform(BRepPrimAPI_MakeBox(10, 20, 30).Shape(), transform, True).Shape()
        path = Path(self.data.name) / "moved.step"
        write_step(path, shape)
        meshes, _ = read_step(path)
        vertices = np.concatenate([m.vertices for m in meshes])
        np.testing.assert_allclose(vertices.min(axis=0), [100, 200, 300])
        np.testing.assert_allclose(vertices.max(axis=0), [110, 220, 330])

    def test_crud_restore_and_exact_bytes_identity(self):
        project = self.save_comment("  Saved note  ")
        record = project["comments"][0]
        self.assertEqual(record["text"], "Saved note")
        project = self.workspace.save_annotation(self.mid, self.key, "comments", {"text": "Edited"}, record["id"])
        self.assertEqual(project["comments"][0]["createdAt"], record["createdAt"])
        renamed = Path(self.data.name) / "renamed.stp"
        renamed.write_bytes(self.box.read_bytes())
        restored = Workspace(self.data.name).open_step(renamed)
        self.assertEqual(restored["comments"][0]["text"], "Edited")
        with self.assertRaises(ValueError):
            self.workspace.delete_annotation(self.mid, "comments", record["id"], False)
        with self.assertRaises(ValueError):
            self.workspace.save_annotation(self.mid, self.project["faces"][1]["key"], "comments", {"text": "Moved"}, record["id"])
        project = self.workspace.delete_annotation(self.mid, "comments", record["id"], True)
        self.assertEqual(project["comments"], [])

    def test_all_condition_types_and_whole_face_highlight(self):
        for kind, values in (("fixed", {}), ("displacement", {"x": 0, "y": 0, "z": 0}),
                             ("force", {"x": 10, "y": -2, "z": 0}), ("pressure", {"magnitude": -5})):
            project = self.workspace.save_annotation(self.mid, self.key, "boundaryConditions", {"type": kind, "values": values})
        self.assertEqual(len(project["boundaryConditions"]), 4)
        preview = trimesh.load(self.workspace.preview(self.mid, self.key), force="scene")
        self.assertEqual(len(preview.geometry), 6)
        selected = preview.geometry[self.key]
        self.assertEqual(len(selected.faces), self.project["faces"][0]["triangleCount"])
        self.assertTrue(np.all(selected.visual.vertex_colors == [255, 199, 106, 255]))

    def test_invalid_conditions_do_not_write(self):
        for kind, values in (("force", {"x": 0, "y": 0, "z": 0}), ("pressure", {"magnitude": 0}),
                             ("pressure", {"magnitude": float("nan")}), ("force", {"x": True, "y": 0, "z": 0})):
            with self.assertRaises(ValueError):
                self.workspace.save_annotation(self.mid, self.key, "boundaryConditions", {"type": kind, "values": values})
        self.assertEqual(self.workspace.get(self.mid)["boundaryConditions"], [])
        with self.assertRaises(ValueError):
            self.workspace.save_annotation(self.mid, "unknown", "comments", {"text": "wrong face"})

    def test_viewer_payload_preserves_python_face_identity_and_ranges(self):
        project = self.workspace.open_step(self.cylinder)
        state = json.loads(self.workspace.viewer_state(project["id"], project["faces"][0]["key"]))
        geometry = json.loads((self.workspace.root / "previews" / f'{project["id"]}-viewer.json').read_text())
        identities = geometry["faceIdentities"]["occurrence-0:mesh:0:slot:0"]
        self.assertEqual([f["key"] for f in identities], [f["key"] for f in project["faces"]])
        ranges = geometry["result"]["meshes"][0]["brep_faces"]
        self.assertEqual(ranges[0]["first"], 0)
        for metadata, interval in zip(project["faces"], ranges):
            self.assertEqual(metadata["triangleCount"], interval["last"] - interval["first"] + 1)
        self.assertEqual(state["selected"], project["faces"][0]["key"])
        self.assertIn("/gradio_api/file=", state["geometryUrl"])

    def test_export_import_atomic_validation_and_legacy(self):
        project = self.save_comment()
        self.workspace.save_annotation(self.mid, self.key, "boundaryConditions", {"type": "fixed", "values": {}})
        exported = Path(self.workspace.export_annotations(self.mid))
        document = json.loads(exported.read_text())
        self.assertEqual(document["units"]["pressure"], "MPa")
        self.assertEqual(document["faceMapping"], "python-ocp-v1")
        document["comments"][0]["text"] = "Imported edit"
        document["boundaryConditions"][0]["values"] = {"magnitude": 0}
        document["boundaryConditions"][0]["type"] = "pressure"
        exported.write_text(json.dumps(document))
        with self.assertRaises(ValueError):
            self.workspace.import_annotations(self.mid, exported)
        self.assertEqual(self.workspace.get(self.mid)["comments"], project["comments"])
        document["schemaVersion"] = 1
        del document["boundaryConditions"]
        document["comments"][0]["faceKey"] = "browser-occurrence:face:1"
        exported.write_text(json.dumps(document))
        result = self.workspace.import_annotations(self.mid, exported)
        self.assertEqual(result["comments"][0]["text"], "Imported edit")
        self.assertEqual(len(result["boundaryConditions"]), 1)
        self.assertEqual(result["comments"][0]["faceKey"], "browser-occurrence:face:1")
        document["modelId"] = "other-model"
        with self.assertRaises(ValueError):
            validate_annotations(document, self.mid)

    def test_invalid_annotation_fields(self):
        self.save_comment()
        original = self.workspace.project_snapshot(self.mid)
        for field, value in (("text", " "), ("createdAt", "bad"), ("anchor", [1, 2]), ("modelId", "other")):
            document = copy.deepcopy(original)
            document["comments"][0][field] = value
            with self.assertRaises(ValueError):
                validate_annotations(document, self.mid)
        original["comments"].append(original["comments"][0])
        with self.assertRaises(ValueError):
            validate_annotations(original, self.mid)

    def test_invalid_step_preserves_projects(self):
        broken = Path(self.data.name) / "broken.step"
        broken.write_text("not a STEP model")
        with self.assertRaises(ValueError):
            self.workspace.open_step(broken)
        self.assertEqual(len(self.workspace.projects()), 1)

    def test_gradio_construction_and_callback_workflow(self):
        from gradio_app.app import build_app
        app = build_app(self.workspace)
        callbacks = {fn.fn.__name__: fn.fn for fn in app.fns.values() if fn.fn}
        opened = callbacks["open_file"](str(self.box))
        self.assertEqual(len(opened), 18)
        result = callbacks["write_comment"](self.mid, self.key, None, "From native Gradio")
        self.assertEqual(result[0], self.mid)
        record = self.workspace.get(self.mid)["comments"][0]
        edit = callbacks["navigate_comment"](self.mid, record["id"])
        self.assertEqual(edit[8], "From native Gradio")
        result = callbacks["write_condition"](self.mid, self.key, None, "force", 1, 2, 3, 0)
        self.assertIn("1 conditions", result[7])
        import gradio as gr
        picked = callbacks["pick_face"](self.mid, gr.EventData(None, {"modelId": self.mid, "faceKey": self.key}))
        self.assertEqual(json.loads(picked[1])["selected"], self.key)
        stale = callbacks["pick_face"](self.mid, gr.EventData(None, {"modelId": "old-model", "faceKey": self.key}))
        self.assertTrue(all(value == gr.skip() for value in stale))

    def test_live_gradio_upload_and_save(self):
        from gradio_client import Client, handle_file
        from gradio_app.app import build_app
        from gradio_app.viewer import STATIC
        app = build_app(self.workspace)
        try:
            _, url, _ = app.queue().launch(
                server_name="127.0.0.1", prevent_thread_lock=True, quiet=True,
                allowed_paths=[str(STATIC), str(self.workspace.root / "previews"), str(self.workspace.root / "exports")],
            )
            client = Client(url, verbose=False)
            result = client.predict(handle_file(str(self.box)), api_name="/open_file")
            self.assertTrue(any(isinstance(value, str) and "6 faces" in value for value in result))
            client.predict(self.key, None, "Live API comment", api_name="/write_comment")
            record = self.workspace.get(self.mid)["comments"][0]
            self.assertEqual(record["text"], "Live API comment")
            client.predict(record["id"], api_name="/navigate_comment")
            client.predict(self.key, record["id"], "Edited via API", api_name="/write_comment")
            self.assertEqual(self.workspace.get(self.mid)["comments"][0]["text"], "Edited via API")
            client.predict(self.key, None, "pressure", 0, 0, 0, -2, api_name="/write_condition")
            self.assertEqual(self.workspace.get(self.mid)["boundaryConditions"][0]["values"], {"magnitude": -2})
        finally:
            app.close()


if __name__ == "__main__":
    unittest.main()
