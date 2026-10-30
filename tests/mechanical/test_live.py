"""Opt-in: set MECHANICAL_TEST_PYTHON to a Python with PyMechanical 0.12.7.

Uses synthetic geometry only; writes artifacts beneath test-results/.
"""

import json
import math
import os
from pathlib import Path
import unittest
import uuid

from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs

from gradio_app.backend import Workspace
from gradio_app.simulation import run_project


@unittest.skipUnless(os.environ.get("MECHANICAL_TEST_PYTHON"), "Explicit opt-in required for a licensed Mechanical solve")
class MechanicalSmokeTests(unittest.TestCase):
    def test_axial_cylinder_force_pressure_displacement(self):
        root = Path("test-results") / ("mechanical-live-" + uuid.uuid4().hex[:10])
        root.mkdir(parents=True)
        source = root / "cylinder.step"
        writer = STEPControl_Writer()
        writer.Transfer(BRepPrimAPI_MakeCylinder(5, 20).Shape(), STEPControl_AsIs)
        writer.Write(str(source.resolve()))
        for kind, values in (("force", {"x": 0, "y": 0, "z": 1000}),
                             ("pressure", {"magnitude": -1000 / (25 * math.pi)}),
                             ("displacement", {"x": 0, "y": 0, "z": 0.001})):
            with self.subTest(kind=kind):
                workspace = Workspace(root / kind)
                project = workspace.open_step(source)
                bottom = min(project["faces"], key=lambda face: face["centroidMm"][2])
                top = max(project["faces"], key=lambda face: face["centroidMm"][2])
                workspace.save_annotation(project["id"], bottom["key"], "boundaryConditions", {"type": "fixed", "values": {}})
                workspace.save_annotation(project["id"], top["key"], "boundaryConditions", {"type": kind, "values": values})
                result = run_project(workspace, project["id"], os.environ["MECHANICAL_TEST_PYTHON"], 3)
                print(json.dumps(result["report"], indent=2), flush=True)
                self.assertEqual(result["report"]["status"], "succeeded", str(result["directory"]))
                self.assertEqual(len(result["images"]), 2)
                self.assertTrue(Path(result["archive"]).is_file())
                results = result["report"]["results"]
                expected = 0.001 if kind == "displacement" else 1000 * 20 / (200000 * 25 * math.pi)
                self.assertAlmostEqual(results["totalDeformation"]["maximum"], expected, delta=expected * 0.06)
                self.assertGreater(results["vonMisesStress"]["maximum"], 0)


if __name__ == "__main__":
    unittest.main()
