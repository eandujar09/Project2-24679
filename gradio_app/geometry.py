"""OpenCascade STEP import. Face IDs belong to this importer, not to Ansys."""

from pathlib import Path
import json

import numpy as np
import trimesh
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_Curve
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepGProp import BRepGProp
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.GProp import GProp_GProps
from OCP.GCPnts import GCPnts_QuasiUniformDeflection
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_IN, TopAbs_SOLID, TopAbs_EDGE, TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer, TopExp
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Pnt2d

FACE_NAMESPACE = "python-ocp-v1"
COLORS = {
    "fixed": [182, 154, 255, 255],
    "displacement": [104, 224, 167, 255],
    "force": [255, 141, 115, 255],
    "pressure": [115, 191, 255, 255],
}


def read_shape(path: Path):
    reader = STEPControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise ValueError("OpenCascade could not read this STEP file.")
    reader.SetSystemLengthUnit(1.0)  # OCCT length unit: millimeters.
    if not reader.TransferRoots():
        raise ValueError("The STEP file contains no transferable geometry.")
    shape = reader.OneShape()
    if shape.IsNull():
        raise ValueError("The STEP file contains no shape.")
    return shape


def read_step(path: Path):
    shape = read_shape(path)
    BRepMesh_IncrementalMesh(shape, 0.1, False, 0.35, True).Perform()
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    meshes, metadata = [], []
    index = 0
    while explorer.More():
        index += 1
        face = TopoDS.Face_s(explorer.Current())
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is None or triangulation.NbTriangles() == 0:
            raise ValueError(f"CAD face {index} could not be tessellated.")
        transform = location.Transformation()
        vertices = []
        for i in range(1, triangulation.NbNodes() + 1):
            point = triangulation.Node(i).Transformed(transform)
            vertices.append([point.X(), point.Y(), point.Z()])
        triangles = np.array([
            triangulation.Triangle(i).Get()
            for i in range(1, triangulation.NbTriangles() + 1)
        ]) - 1
        if face.Orientation() == TopAbs_REVERSED:
            triangles = triangles[:, ::-1]
        mesh = trimesh.Trimesh(vertices=vertices, faces=triangles, process=False)
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        center = props.CentreOfMass()
        key = f"{FACE_NAMESPACE}:face:{index}"
        meshes.append(mesh)
        metadata.append({
            "key": key, "index": index, "areaMm2": props.Mass(),
            "centroidMm": [center.X(), center.Y(), center.Z()],
            "triangleCount": len(triangles),
        })
        explorer.Next()
    if not meshes:
        raise ValueError("No CAD faces found in the STEP file.")
    return meshes, metadata


def interior_surface_samples(face, target=9):
    """Deterministic interior sampling of the *trimmed* face, not just its UV box.

    UV triangles provide seeds only. Every accepted point is classified strictly
    inside the original B-rep and evaluated on its exact parametric surface.
    """
    surface = BRepAdaptor_Surface(face)
    bounds = BRepTools.UVBounds_s(face)
    if not all(np.isfinite(bounds)):
        return [], "unbounded-uv"
    samples = []
    sign = -1 if face.Orientation() == TopAbs_REVERSED else 1

    def add(u, v):
        if BRepClass_FaceClassifier(face, gp_Pnt2d(float(u), float(v)), 1e-7).State() != TopAbs_IN:
            return
        local = BRepLProp_SLProps(surface, float(u), float(v), 1, 1e-9)
        if not local.IsNormalDefined():
            return
        point, normal = surface.Value(float(u), float(v)), local.Normal()
        xyz = [point.X(), point.Y(), point.Z()]
        if any(sum((a - b) ** 2 for a, b in zip(xyz, sample["pointMm"])) < 1e-20 for sample in samples):
            return
        samples.append({"pointMm": xyz, "normal": [sign * normal.X(), sign * normal.Y(), sign * normal.Z()]})

    for fu in (0.2, 0.5, 0.8):
        for fv in (0.2, 0.5, 0.8):
            add(bounds[0] + (bounds[1] - bounds[0]) * fu, bounds[2] + (bounds[3] - bounds[2]) * fv)
    if len(samples) >= target:
        return samples[:target], "uv-grid"

    # A thin diagonal patch or ring can contain none of the 3x3 grid points.
    # Tessellate the actual face, then use *UV* barycentric seeds: 3D chord
    # centroids would lie off the exact surface of a curved face.
    location = TopLoc_Location()
    triangulation = BRep_Tool.Triangulation_s(face, location)
    if triangulation is None or not triangulation.HasUVNodes():
        BRepMesh_IncrementalMesh(face, 0.01, False, 0.2, True).Perform()
        triangulation = BRep_Tool.Triangulation_s(face, location)
    if triangulation is not None and triangulation.HasUVNodes():
        seeds = []
        for i in range(1, triangulation.NbTriangles() + 1):
            uv = [triangulation.UVNode(node) for node in triangulation.Triangle(i).Get()]
            area = abs((uv[1].X() - uv[0].X()) * (uv[2].Y() - uv[0].Y()) -
                       (uv[2].X() - uv[0].X()) * (uv[1].Y() - uv[0].Y()))
            seeds.append((area, i, uv))
        seeds.sort(key=lambda seed: (-seed[0], seed[1]))
        for weights in ((1/3, 1/3, 1/3), (0.6, 0.2, 0.2), (0.2, 0.6, 0.2), (0.2, 0.2, 0.6),
                        (0.8, 0.1, 0.1), (0.1, 0.8, 0.1), (0.1, 0.1, 0.8),
                        (0.45, 0.45, 0.1), (0.45, 0.1, 0.45), (0.1, 0.45, 0.45)):
            for _, _, uv in seeds:
                add(sum(w * p.X() for w, p in zip(weights, uv)), sum(w * p.Y() for w, p in zip(weights, uv)))
                if len(samples) >= target:
                    return samples[:target], "trimmed-uv-triangles"

    # Last-resort bounded search for unusually concave/periodic UV trims.
    for resolution in (17, 65):
        for fu in np.linspace(0, 1, resolution + 2)[1:-1]:
            for fv in np.linspace(0, 1, resolution + 2)[1:-1]:
                add(bounds[0] + (bounds[1] - bounds[0]) * fu, bounds[2] + (bounds[3] - bounds[2]) * fv)
                if len(samples) >= target:
                    return samples[:target], "adaptive-uv-grid"
    return samples, "trimmed-uv-search"


def mechanical_signatures(path):
    """Exact interior surface samples for conservative cross-kernel matching."""
    shape = read_shape(path)
    solids = TopExp_Explorer(shape, TopAbs_SOLID)
    count = 0
    while solids.More():
        count += 1
        solids.Next()
    if count != 1:
        raise ValueError("The deterministic solver currently requires exactly one solid (no assemblies, shells, or beams).")
    signatures = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        index = len(signatures) + 1
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        center = props.CentreOfMass()
        surface = BRepAdaptor_Surface(face)
        samples, sampling_method = interior_surface_samples(face)
        if len(samples) < 3:
            raise ValueError(f"Face {index} has only {len(samples)} verified distinct interior samples after adaptive trimmed-face sampling; safe mapping needs at least 3.")
        edge_map, vertex_map = TopTools_IndexedMapOfShape(), TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(face, TopAbs_EDGE, edge_map)
        TopExp.MapShapes_s(face, TopAbs_VERTEX, vertex_map)
        edges, vertices = [], []
        for edge_index in range(1, edge_map.Extent() + 1):
            edge = TopoDS.Edge_s(edge_map.FindKey(edge_index))
            # A periodic surface's artificial seam is not a trim boundary;
            # Mechanical does not expose it in the face's boundary-edge list.
            if BRep_Tool.IsClosed_s(edge, face):
                continue
            curve = BRepAdaptor_Curve(edge)
            start, end = curve.FirstParameter(), curve.LastParameter()
            points = []
            for fraction in np.linspace(0, 1, 9):
                point = curve.Value(start + (end - start) * float(fraction))
                points.append([point.X(), point.Y(), point.Z()])
            # A fine curve polyline supports reverse boundary-coverage checks
            # when the CAD translators split the same boundary differently.
            approximation = GCPnts_QuasiUniformDeflection(curve, 1e-6, start, end)
            if not approximation.IsDone():
                raise ValueError(f"Face {index} boundary approximation failed.")
            polyline = []
            for node in range(1, approximation.NbPoints() + 1):
                point = approximation.Value(node)
                polyline.append([point.X(), point.Y(), point.Z()])
            edges.append({"pointsMm": points, "polylineMm": polyline, "polylineDeflectionMm": 1e-6})
        for vertex_index in range(1, vertex_map.Extent() + 1):
            point = BRep_Tool.Pnt_s(TopoDS.Vertex_s(vertex_map.FindKey(vertex_index)))
            vertices.append([point.X(), point.Y(), point.Z()])
        signatures.append({"key": f"{FACE_NAMESPACE}:face:{index}", "index": index,
                           "areaMm2": props.Mass(), "centroidMm": [center.X(), center.Y(), center.Z()],
                           "surfaceType": str(surface.GetType()).split("GeomAbs_")[-1], "samples": samples,
                           "samplingMethod": sampling_method, "edges": edges, "verticesMm": vertices})
        explorer.Next()
    return signatures


def save_meshes(path, meshes):
    arrays = {}
    for i, mesh in enumerate(meshes):
        arrays[f"v{i}"] = mesh.vertices
        arrays[f"f{i}"] = mesh.faces
    np.savez_compressed(path, **arrays)


def viewer_geometry(cache, metadata, destination):
    """The shared JS viewer consumes Python's exact triangle ranges and keys."""
    positions, indices, ranges = [], [], []
    vertex_offset = 0
    with np.load(cache, allow_pickle=False) as arrays:
        for i, face in enumerate(metadata):
            vertices, triangles = arrays[f"v{i}"], arrays[f"f{i}"]
            first = len(indices) // 3
            positions.extend(vertices.reshape(-1).tolist())
            indices.extend((triangles + vertex_offset).reshape(-1).tolist())
            ranges.append({"first": first, "last": len(indices) // 3 - 1})
            vertex_offset += len(vertices)
    payload = {
        "result": {"root": {"name": "Python CAD", "meshes": [0]}, "meshes": [{
            "attributes": {"position": {"array": positions}},
            "index": {"array": indices}, "brep_faces": ranges,
        }]},
        "faceIdentities": {"occurrence-0:mesh:0:slot:0": [
            {"key": face["key"], "index": face["index"]} for face in metadata
        ]},
    }
    destination.write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    return destination


def preview(cache, metadata, conditions, selected, destination):
    scene = trimesh.Scene()
    by_face = {item["faceKey"]: item["type"] for item in conditions}
    with np.load(cache, allow_pickle=False) as arrays:
        for i, face in enumerate(metadata):
            key = face["key"]
            mesh = trimesh.Trimesh(arrays[f"v{i}"], arrays[f"f{i}"], process=False)
            color = COLORS.get(by_face.get(key), [145, 172, 191, 255])
            if key == selected:
                color = [255, 199, 106, 255]
            # Each CAD face owns its vertices; uniform vertex colors preserve
            # whole-face tints without requiring scipy's face-to-vertex conversion.
            mesh.visual.vertex_colors = color
            scene.add_geometry(mesh, node_name=key, geom_name=key)
    scene.export(str(destination), file_type="glb")
    return str(destination)
