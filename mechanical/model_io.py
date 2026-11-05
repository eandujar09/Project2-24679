"""Import arbitrary STEP geometry and attempt exact viewer-to-Mechanical face mapping."""
import math
from .contract import match_faces


def import_geometry(request, output, ns):
    Model, ExtAPI, Ansys = ns['Model'], ns['ExtAPI'], ns['Ansys']
    DataModelObjectCategory = ns['DataModelObjectCategory']
    GeometryImportPreference = ns['GeometryImportPreference']
    preferences = Ansys.ACT.Mechanical.Utilities.GeometryImportPreferences()
    preferences.FacetQuality = GeometryImportPreference.FacetQuality.VeryFine
    importer = Model.GeometryImportGroup.AddGeometryImport()
    importer.Import(str(output / "source.step"), GeometryImportPreference.Format.Automatic, preferences)
    bodies = list(Model.Geometry.GetChildren(DataModelObjectCategory.Body, True))
    if str(ExtAPI.DataModel.GeoData.Unit) != "mm":
        raise ValueError("Mechanical CAD geometry is not in millimeters.")
    faces = {int(f.Id): f for body in bodies for f in body.GetGeoBody().Faces}
    # Some translators expose periodic seam edges; others omit them. In a
    # closed single solid, a real inter-face trim edge has two incident
    # faces, whereas a surface's artificial seam belongs only to itself.
    face_edges = {key: [edge for edge in face.Edges if len({int(owner.Id) for owner in edge.Faces}) > 1]
                  for key, face in faces.items()}
    edges = {int(edge.Id): edge for boundary in face_edges.values() for edge in boundary}
    candidates = [{"id": key, "areaMm2": float(face.Area), "centroidMm": list(face.Centroid),
                   "verticesMm": [[float(v.X), float(v.Y), float(v.Z)] for v in face.Vertices],
                   "edgeIds": [int(edge.Id) for edge in face_edges[key]],
                   "boundarySamplesMm": [list(edge.PointAtParam(float(edge.Extents[0]) +
                                          (float(edge.Extents[1]) - float(edge.Extents[0])) * i / 64.0))
                                         for edge in face_edges[key] for i in range(65)]}
                  for key, face in faces.items()]

    def evaluate(face_id, point):
        face = faces[face_id]
        uv = face.ParamAtPoint(point)
        return list(face.PointAtParam(uv[0], uv[1])), list(face.NormalAtParam(uv[0], uv[1]))

    def evaluate_edge(edge_id, point):
        edge = edges[edge_id]
        low, high = sorted(float(t) for t in edge.Extents)
        parameter = float(edge.ParamAtPoint(point))
        if distance_between_endpoints(edge) < 1e-7 and high > low:
            parameter = low + (parameter - low) % (high - low)
        parameter = max(low, min(high, parameter))
        return list(edge.PointAtParam(parameter))

    def distance_between_endpoints(edge):
        a, b = edge.StartVertex, edge.EndVertex
        return math.sqrt((a.X - b.X) ** 2 + (a.Y - b.Y) ** 2 + (a.Z - b.Z) ** 2)

    mapping, evidence, warning = {}, [], request.get("faceMappingWarning")
    if request.get("faceSignatures"):
        try:
            mapping, evidence = match_faces(request["faceSignatures"], candidates, evaluate, evaluate_edge=evaluate_edge)
        except ValueError as exc:
            warning = str(exc)
            evidence = getattr(exc, 'diagnostics', [])
    else:
        warning = warning or 'Exact source face signatures are unavailable.'
    geometry = {'bodies': [{'id': int(b.GetGeoBody().Id), 'name': str(b.Name),
                            'type': str(b.GetGeoBody().BodyType), 'material': str(b.Material),
                            'faceIds': [int(f.Id) for f in b.GetGeoBody().Faces]} for b in bodies],
                'faces': [{k: f[k] for k in ('id', 'areaMm2', 'centroidMm')} for f in candidates],
                'faceMappingVerified': bool(mapping), 'faceMappingWarning': warning,
                'namedSelections': [{'name': str(n.Name), 'ids': list(n.Location.Ids)}
                                    for n in (Model.NamedSelections.Children if Model.NamedSelections is not None else [])]}
    return bodies, mapping, evidence, geometry
