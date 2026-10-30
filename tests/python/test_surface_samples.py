import math
import unittest

from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCP.TopAbs import TopAbs_FACE, TopAbs_IN
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Pln, gp_Pnt, gp_Dir

from gradio_app.geometry import interior_surface_samples


class InteriorSamplingTests(unittest.TestCase):
    def assert_valid(self, face, samples):
        self.assertGreaterEqual(len(samples), 3)
        self.assertEqual(len(samples), len({tuple(s["pointMm"]) for s in samples}))
        for sample in samples:
            point = gp_Pnt(*sample["pointMm"])
            self.assertEqual(BRepClass_FaceClassifier(face, point, 1e-7).State(), TopAbs_IN)
            self.assertAlmostEqual(sum(n*n for n in sample["normal"]), 1, places=10)

    def test_thin_diagonal_face_missed_by_all_coarse_grid_points(self):
        polygon = BRepBuilderAPI_MakePolygon()
        for coordinates in ((0, 0, 0), (100, 100, 0), (100, 100.001, 0)):
            polygon.Add(gp_Pnt(*coordinates))
        polygon.Close()
        face = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), polygon.Wire(), True).Face()
        samples, method = interior_surface_samples(face)
        self.assert_valid(face, samples)
        self.assertEqual(len(samples), 9)
        self.assertEqual(method, "trimmed-uv-triangles")
        # Repeating the calculation must give the same exact seed/evaluation order.
        self.assertEqual((samples, method), interior_surface_samples(face))

    def test_curved_points_are_evaluated_on_surface_not_triangle_chords(self):
        explorer = TopExp_Explorer(BRepPrimAPI_MakeCylinder(5, 20).Shape(), TopAbs_FACE)
        while explorer.More():
            face = TopoDS.Face_s(explorer.Current())
            if str(BRepAdaptor_Surface(face).GetType()).endswith("Cylinder"):
                samples, _ = interior_surface_samples(face)
                self.assert_valid(face, samples)
                for sample in samples:
                    x, y, _ = sample["pointMm"]
                    self.assertAlmostEqual(math.hypot(x, y), 5, places=10)
                return
            explorer.Next()
        self.fail("Cylinder fixture has no cylindrical face")


if __name__ == "__main__":
    unittest.main()
