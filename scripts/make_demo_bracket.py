"""Generate the small, original STEP bracket used by the guided demo.

Geometry only: no materials, loads, supports, or Mechanical scripts are embedded.
Run with the CAD application's Python environment from any working directory.
"""
import argparse
from math import sqrt
from pathlib import Path

from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.GC import GC_MakeArcOfCircle
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.gp import gp_Pnt, gp_Vec

ROOT = Path(__file__).resolve().parents[1]


def make_bracket():
    """80 mm reach, 60 mm height, 30 mm width, 8 mm wall, R6 inside bend."""
    wire = BRepBuilderAPI_MakeWire()

    def line(a, b):
        wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(*a), gp_Pnt(*b)).Edge())

    line((0, 0, 0), (80, 0, 0))
    line((80, 0, 0), (80, 0, 8))
    line((80, 0, 8), (14, 0, 8))
    arc = GC_MakeArcOfCircle(gp_Pnt(14, 0, 8),
                             gp_Pnt(14 - 6 / sqrt(2), 0, 14 - 6 / sqrt(2)),
                             gp_Pnt(8, 0, 14)).Value()
    wire.Add(BRepBuilderAPI_MakeEdge(arc).Edge())
    line((8, 0, 14), (8, 0, 60))
    line((8, 0, 60), (0, 0, 60))
    line((0, 0, 60), (0, 0, 0))
    face = BRepBuilderAPI_MakeFace(wire.Wire()).Face()
    shape = BRepPrimAPI_MakePrism(face, gp_Vec(0, 30, 0)).Shape()
    if not BRepCheck_Analyzer(shape).IsValid():
        raise RuntimeError('The generated bracket is not a valid solid.')
    return shape


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'examples/simple-bracket/simple-bracket.step')
    path = parser.parse_args().output
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = STEPControl_Writer()
    if writer.Transfer(make_bracket(), STEPControl_AsIs) != IFSelect_RetDone:
        raise RuntimeError('Could not transfer the demo solid to STEP.')
    if writer.Write(str(path)) != IFSelect_RetDone:
        raise RuntimeError('Could not write the demo STEP file.')
    # STEP names the source file in its header. Keep the checked-in demo portable.
    text = path.read_text()
    text = text.replace(str(path), path.name)
    path.write_text('\n'.join(line.rstrip() for line in text.splitlines()) + '\n')
    print(path)


if __name__ == '__main__':
    main()
