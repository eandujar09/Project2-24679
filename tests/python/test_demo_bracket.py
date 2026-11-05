"""The portable demo must have the two unambiguous faces described to users."""
from pathlib import Path
import unittest

from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer

from gradio_app.geometry import read_shape, read_step


class DemoBracketTests(unittest.TestCase):
    def test_included_step_has_one_solid_and_distinct_support_and_load_faces(self):
        path = Path(__file__).resolve().parents[2] / 'examples/simple-bracket/simple-bracket.step'
        shape = read_shape(path)
        self.assertTrue(BRepCheck_Analyzer(shape).IsValid())
        solids = TopExp_Explorer(shape, TopAbs_SOLID)
        count = 0
        while solids.More():
            count += 1
            solids.Next()
        self.assertEqual(count, 1)
        meshes, faces = read_step(path)
        self.assertEqual(len(faces), 9)

        def at_x(value):
            return [f for f in faces if all(abs(bound[0] - value) < 1e-6 for bound in f['boundsMm'])]

        support, load = at_x(0), at_x(80)
        self.assertEqual(len(support), 1)
        self.assertEqual(len(load), 1)
        self.assertEqual(support[0]['surfaceType'], 'Plane')
        self.assertEqual(load[0]['surfaceType'], 'Plane')
        self.assertAlmostEqual(support[0]['areaMm2'], 1800)
        self.assertAlmostEqual(load[0]['areaMm2'], 240)
        self.assertNotEqual(support[0]['key'], load[0]['key'])
        vertices = [point for mesh in meshes for point in mesh.vertices]
        for axis, extent in enumerate([80, 30, 60]):
            self.assertAlmostEqual(min(p[axis] for p in vertices), 0)
            self.assertAlmostEqual(max(p[axis] for p in vertices), extent)
