"""Deterministic local CAD preparation, never model-authored code or a solver call."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from .fluid_domain import validate_domain
from .geometry import read_shape, read_step


def solids(shape):
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    result = []
    while explorer.More():
        result.append(TopoDS.Solid_s(explorer.Current()))
        explorer.Next()
    return result


def volume(shape):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    properties = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, properties)
    return properties.Mass()


def checked_boolean(operation, label):
    operation.Build()
    if not operation.IsDone() or operation.Shape().IsNull():
        raise ValueError(label + ' failed. The original CAD has not been changed.')
    return operation.Shape()


def build_domain(source, definition, output):
    """Build one connected, watertight fluid solid and verify the exported STEP.

    An obstacle must be fully inside the enclosure with positive clearance. Open
    internal passages, arbitrary capping and custom domains require separate CAD prep.
    """
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.TopAbs import TopAbs_SHELL, TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer, TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2

    definition = validate_domain(definition['kind'], definition['cadRole'],
                                 definition['parameters'], definition['description'])
    kind, role, p = definition['kind'], definition['cadRole'], definition['parameters']
    if kind not in ('box', 'cylinder') or role not in ('obstacle', 'reference'):
        raise ValueError('Construction supports box/cylinder domains around solid obstacles, or empty volumes from explicit reference geometry. Use a prepared STEP for custom/internal-passage extraction.')
    source, output = Path(source), Path(output)
    if output.exists() or source.resolve() == output.resolve():
        raise ValueError('Domain output must be a new file; never overwrite the source.')
    if kind == 'box':
        lengths = [p['max_'+a] - p['min_'+a] for a in 'xyz']
        if not all(math.isfinite(v) and v > 0 for v in lengths):
            raise ValueError('Box dimensions overflow or are not positive.')
        enclosure = BRepPrimAPI_MakeBox(gp_Pnt(*(p['min_'+a] for a in 'xyz')), *lengths).Shape()
        scale = max(lengths)
    else:
        enclosure = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*(p['origin_'+a] for a in 'xyz')),
                    gp_Dir(*(p['axis_'+a] for a in 'xyz'))), p['radius'], p['length']).Shape()
        scale = max(p['radius'] * 2, p['length'])
    if not BRepCheck_Analyzer(enclosure).IsValid():
        raise ValueError('Enclosure geometry is invalid.')
    enclosure_volume = volume(enclosure)
    if not math.isfinite(enclosure_volume) or enclosure_volume <= 0:
        raise ValueError('Enclosure has no finite positive volume.')
    tolerance = max(1e-6, scale * 1e-8)
    tolerance_volume = max(1e-7, enclosure_volume * 1e-8)
    shell_explorer = TopExp_Explorer(enclosure, TopAbs_SHELL)
    if not shell_explorer.More():
        raise ValueError('Enclosure has no closed boundary shell.')
    shell = TopoDS.Shell_s(shell_explorer.Current())
    obstacle_volume, clearance = 0.0, None
    fluid = enclosure
    if role == 'obstacle':
        obstacle = read_shape(source)
        obstacle_solids = solids(obstacle)
        if not obstacle_solids or not BRepCheck_Analyzer(obstacle).IsValid():
            raise ValueError('Obstacle CAD must contain valid closed solids, not open surfaces.')
        all_faces,solid_faces = TopTools_IndexedMapOfShape(),TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(obstacle,TopAbs_FACE,all_faces)
        for solid in obstacle_solids:
            TopExp.MapShapes_s(solid,TopAbs_FACE,solid_faces)
        if all_faces.Extent() != solid_faces.Extent():
            raise ValueError('Obstacle CAD includes open/non-solid surfaces; provide closed obstacle solids only.')
        obstacle_volume = volume(obstacle)
        if not math.isfinite(obstacle_volume) or obstacle_volume <= tolerance_volume:
            raise ValueError('Obstacle CAD has no resolvable positive solid volume.')
        common = checked_boolean(BRepAlgoAPI_Common(enclosure, obstacle), 'Enclosure/obstacle intersection')
        if abs(volume(common) - obstacle_volume) > max(tolerance_volume, obstacle_volume * 1e-8):
            raise ValueError('The enclosure does not completely contain the obstacle. Increase its dimensions.')
        distance = BRepExtrema_DistShapeShape(obstacle, shell)
        distance.Perform()
        if not distance.IsDone():
            raise ValueError('Obstacle clearance could not be measured.')
        clearance = distance.Value()
        if clearance <= tolerance:
            raise ValueError('The enclosure touches the obstacle (zero or unresolved clearance). Propose positive clearance on the touching sides, preserving the user\'s fixed bounds.')
        fluid = checked_boolean(BRepAlgoAPI_Cut(enclosure, obstacle), 'Obstacle subtraction')
    connected = solids(fluid)
    if len(connected) != 1:
        raise ValueError(f'The fluid domain has {len(connected)} disconnected solid regions; one connected region is required. Review sealed cavities or change the enclosure.')
    fluid = connected[0]
    if not BRepCheck_Analyzer(fluid).IsValid():
        raise ValueError('The subtracted fluid domain is not a valid watertight solid.')
    fluid_volume = volume(fluid)
    if fluid_volume <= tolerance_volume or abs(fluid_volume - (enclosure_volume - obstacle_volume)) > tolerance_volume:
        raise ValueError('Fluid volume does not agree with enclosure minus obstacle volume.')
    writer = STEPControl_Writer()
    writer.Transfer(fluid, STEPControl_AsIs)
    if writer.Write(str(output)) != IFSelect_RetDone:
        raise ValueError('Fluid STEP export failed.')
    exported = read_shape(output)
    exported_solids = solids(exported)
    if (len(exported_solids) != 1 or not BRepCheck_Analyzer(exported).IsValid()
            or abs(volume(exported) - fluid_volume) > max(tolerance_volume, fluid_volume * 1e-6)):
        raise ValueError('The exported STEP failed watertightness/connectivity/volume verification.')
    _, descriptors = read_step(output)
    explorer = TopExp_Explorer(exported, TopAbs_FACE)
    roles = {}
    for face in descriptors:
        boundary = TopoDS.Face_s(explorer.Current())
        distance = BRepExtrema_DistShapeShape(boundary, shell)
        distance.Perform()
        if not distance.IsDone():
            raise ValueError('Derived face provenance could not be measured.')
        boundary_role = 'obstacle_wall' if distance.Value() > tolerance else 'enclosure'
        if boundary_role == 'enclosure' and kind == 'box':
            for a, axis in enumerate('xyz'):
                lo, hi = face['boundsMm'][0][a], face['boundsMm'][1][a]
                for side in ('min', 'max'):
                    if abs(lo - p[side+'_'+axis]) <= tolerance and abs(hi - lo) <= tolerance:
                        boundary_role = side + '_' + axis
        roles[face['key']] = boundary_role
        explorer.Next()
    return {'status':'succeeded', 'kernel':'OpenCascade', 'lengthUnit':'mm', 'kind':kind,
            'operation':'enclosure-minus-obstacle' if role == 'obstacle' else 'empty-fluid-volume',
            'connectedRegions':1, 'watertight':True, 'sourceSHA256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'enclosureVolumeMm3':enclosure_volume, 'obstacleVolumeMm3':obstacle_volume,
            'fluidVolumeMm3':fluid_volume, 'minimumClearanceMm':clearance,
            'geometricToleranceMm':tolerance, 'faceRoles':roles,
            'note':'Geometric clearance is verified; CFD domain-size independence is not established.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True, type=Path)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding='utf-8'))
    try:
        report = build_domain(request['source'], request['definition'], request['output'])
    except Exception as exc:
        report = {'status':'failed', 'error':str(exc)}
    Path(request['report']).write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    return 0 if report['status'] == 'succeeded' else 1


if __name__ == '__main__':
    raise SystemExit(main())
