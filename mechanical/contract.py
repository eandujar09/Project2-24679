"""Pure-Python job validation, canonical load aggregation and face matching."""

import hashlib
import json
import math
from pathlib import Path


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


class FaceMappingError(ValueError):
    def __init__(self, message, diagnostics):
        super().__init__(message)
        self.diagnostics = diagnostics


def normalize_conditions(records, face_keys):
    if not isinstance(records, list) or not records:
        raise ValueError("Annotate boundary conditions before running a simulation.")
    seen, groups = set(), {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"] or record["id"] in seen:
            raise ValueError("Invalid or duplicate boundary-condition IDs.")
        seen.add(record["id"])
        key, kind, values = record.get("faceKey"), record.get("type"), record.get("values")
        if not isinstance(key, str) or key not in face_keys:
            raise ValueError(f"Boundary condition {record['id']} has an unmapped face.")
        if kind not in ("fixed", "displacement", "force", "pressure") or not isinstance(values, dict):
            raise ValueError("Unsupported condition type or values.")
        if kind in ("force", "displacement"):
            if not all(finite(values.get(axis)) for axis in "xyz"):
                raise ValueError("Vector components must be finite numbers.")
            if kind == "force" and not any(values[axis] for axis in "xyz"):
                raise ValueError("A force must have a nonzero resultant.")
        if kind == "pressure" and (not finite(values.get("magnitude")) or values["magnitude"] == 0):
            raise ValueError("Pressure must be finite and nonzero.")
        groups.setdefault(key, []).append(record)
    applied = []
    for key in sorted(groups):
        records = sorted(groups[key], key=lambda r: r["id"])
        supports = [r for r in records if r["type"] in ("fixed", "displacement")]
        loads = [r for r in records if r["type"] in ("force", "pressure")]
        if len(supports) > 1 or (supports and loads):
            raise ValueError(f"Face {key} has conflicting supports or loads on a constrained face.")
        if supports:
            r = supports[0]
            applied.append({"faceKey": key, "type": r["type"], "values": dict(r["values"]), "sourceIds": [r["id"]]})
        for kind in ("force", "pressure"):
            selected = [r for r in loads if r["type"] == kind]
            if selected:
                fields = "xyz" if kind == "force" else ("magnitude",)
                values = {field: math.fsum(r["values"][field] for r in selected) for field in fields}
                if not all(finite(value) for value in values.values()):
                    raise ValueError("Combined loads exceed the supported numeric range.")
                if any(values.values()):
                    applied.append({"faceKey": key, "type": kind, "values": values, "sourceIds": [r["id"] for r in selected]})
    if not any(r["type"] in ("fixed", "displacement") for r in applied):
        raise ValueError("At least one fixed support or prescribed displacement is required. Weak springs are disabled.")
    if not any(r["type"] in ("force", "pressure") or (r["type"] == "displacement" and any(r["values"].values())) for r in applied):
        raise ValueError("The setup has no nonzero load or prescribed displacement after aggregation.")
    return applied


def validate_request(request):
    if request.get("schemaVersion") != 1 or request.get("faceMapping") != "python-ocp-v1":
        raise ValueError("Unsupported Mechanical request or CAD face namespace.")
    step = Path(request["stepFile"])
    actual = hashlib.sha256(step.read_bytes()).hexdigest()
    if actual != request.get("modelId"):
        raise ValueError("STEP SHA-256 mismatch; refusing to run against different geometry.")
    settings = request.get("settings", {})
    if not finite(settings.get("elementSizeMm")) or settings["elementSizeMm"] <= 0:
        raise ValueError("Element size must be positive and finite (mm).")
    if settings.get("material") != "Structural Steel" or settings.get("mechanicalVersion") != 261:
        raise ValueError("This runner currently supports Mechanical 261 with its Structural Steel library material.")
    if settings.get("solverCores") != 1 or settings.get("largeDeflection") is not False:
        raise ValueError("Expected one solver core and small-deflection static structural analysis.")
    if request.get("units") != {"length": "mm", "force": "N", "pressure": "MPa"}:
        raise ValueError("Expected explicit mm/N/MPa units.")
    faces = request.get("faceSignatures")
    if not isinstance(faces, list) or not faces or len({f["key"] for f in faces}) != len(faces):
        raise ValueError("Invalid source face signatures.")
    for face in faces:
        if (not finite(face.get("areaMm2")) or face["areaMm2"] <= 0 or
                len(face.get("centroidMm", [])) != 3 or not all(map(finite, face["centroidMm"])) or
                len(face.get("samples", [])) < 3):
            raise ValueError("Invalid face geometry signature.")
        if not face.get("edges") or not face.get("verticesMm"):
            raise ValueError("This request lacks exact trim-boundary signatures. Regenerate it with the updated app/preparer.")
        point_sets = [face["verticesMm"]] + [edge.get("pointsMm", []) for edge in face["edges"]]
        for edge in face["edges"]:
            if "polylineMm" in edge:
                if len(edge["polylineMm"]) < 2 or not finite(edge.get("polylineDeflectionMm")) or not 0 < edge["polylineDeflectionMm"] < 1e-5:
                    raise ValueError("Invalid trim-boundary polyline accuracy.")
                point_sets.append(edge["polylineMm"])
        if any(not points or any(len(p) != 3 or not all(map(finite, p)) for p in points) for points in point_sets):
            raise ValueError("Invalid exact trim-boundary signature.")
        for sample in face["samples"]:
            if any(len(sample.get(field, [])) != 3 or not all(map(finite, sample[field])) for field in ("pointMm", "normal")):
                raise ValueError("Invalid face surface sample.")
            if abs(sum(value * value for value in sample["normal"]) - 1) > 1e-6:
                raise ValueError("Face sample normals must be unit vectors.")
    records = request.get("boundaryConditions", [])
    if any(r.get("modelId") != actual for r in records):
        raise ValueError("A boundary condition belongs to another model.")
    return normalize_conditions(records, {f["key"] for f in faces})


def boundary_union_errors(source, candidate, evaluate_edge, tolerance):
    """Check the same trimmed boundary despite redundant edge subdivisions.

    Forward points project to exact Mechanical edges. Reverse Mechanical curve
    samples are compared to fine OCP curve polylines, reserving their deflection
    budget from the acceptance tolerance. This remains a finite sampling test.
    """
    edges, target_ids = source["edges"], candidate.get("edgeIds", [])
    target_points = candidate.get("boundarySamplesMm", [])
    if not target_ids or not target_points or not all(edge.get("polylineMm") for edge in edges):
        return None
    budget = max(edge.get("polylineDeflectionMm", float("inf")) for edge in edges)
    if not finite(budget) or not 0 < budget < tolerance / 10:
        return None
    segments = [(a, b) for edge in edges for a, b in zip(edge["polylineMm"], edge["polylineMm"][1:])]
    if not segments:
        return None

    def to_source(point):
        best = float("inf")
        for a, b in segments:
            delta = [y-x for x, y in zip(a, b)]
            squared = sum(d*d for d in delta)
            t = max(0, min(1, sum((p-x)*d for p, x, d in zip(point, a, delta)) / squared)) if squared else 0
            best = min(best, distance(point, [x+t*d for x, d in zip(a, delta)]))
        return best

    def to_target(point):
        return min(distance(point, evaluate_edge(edge_id, point)) for edge_id in target_ids)

    # Nodes lie on exact source curves; reserve the polyline deflection for
    # segment-midpoint checks, which lie on their chords.
    forward_points = [p for edge in edges for p in edge["polylineMm"] + edge["pointsMm"]]
    forward_points.extend([(x+y)/2 for x, y in zip(a, b)] for a, b in segments)
    forward = max(to_target(p) for p in forward_points) + budget
    reverse = max(to_source(p) for p in target_points) + budget
    vertices = max(max(to_target(p) for p in source["verticesMm"]),
                   max(to_source(p) + budget for p in candidate["verticesMm"]))
    return {"forwardBoundaryErrorMm": forward, "reverseBoundaryErrorBoundMm": reverse,
            "maxBoundaryErrorMm": max(forward, reverse), "maxVertexErrorMm": vertices}


def match_faces(signatures, candidates, evaluate, position_tolerance_mm=1e-4, area_relative_tolerance=0.002,
                evaluate_edge=None):
    """Require a unique, one-to-one match, including exact surface points/normals.

    evaluate(candidate_id, point_mm) returns projected surface point and outward
    normal. No numerical ID/order correspondence or nearest-face fallback exists.
    """
    if len(signatures) != len(candidates):
        raise ValueError("Mechanical changed the number of CAD faces; automatic mapping is unsafe.")
    mapping, evidence, used = {}, [], set()
    for source in sorted(signatures, key=lambda f: f["key"]):
        matches, rejected = [], []
        for candidate in sorted(candidates, key=lambda f: f["id"]):
            if (not finite(candidate["areaMm2"]) or len(candidate["centroidMm"]) != 3 or
                    not all(map(finite, candidate["centroidMm"]))):
                raise ValueError("Mechanical returned invalid face geometry.")
            area_error = abs(candidate["areaMm2"] - source["areaMm2"]) / source["areaMm2"]
            centroid_error = distance(candidate["centroidMm"], source["centroidMm"])
            score = {"faceKey": source["key"], "mechanicalFaceId": candidate["id"],
                     "relativeAreaError": area_error, "centroidErrorMm": centroid_error}
            # Mechanical's values are faceted approximations, not exact CAD mass
            # properties. Coarse filtering is safe ONLY with exact trim checks.
            strict_trim = evaluate_edge is not None and bool(source.get("edges")) and bool(source.get("verticesMm"))
            area_limit = 0.02 if strict_trim else area_relative_tolerance
            centroid_limit = 0.1 if strict_trim else position_tolerance_mm
            has_boundary_coverage = (strict_trim and bool(candidate.get("boundarySamplesMm")) and
                                     all(edge.get("polylineMm") for edge in source["edges"]))
            if (area_error > area_limit and not has_boundary_coverage) or centroid_error > centroid_limit:
                rejected.append(dict(score, rejectedBy="coarse area/centroid filter"))
                continue
            boundary_error, vertex_error = None, None
            subdivision_evidence = None
            if strict_trim:
                source_vertices, target_vertices = source["verticesMm"], candidate.get("verticesMm", [])
                source_edges, target_edges = source["edges"], candidate.get("edgeIds", [])
                if (len(source_vertices) != len(target_vertices) or len(source_edges) != len(target_edges) or
                        area_error > area_limit):
                    subdivision_evidence = boundary_union_errors(source, candidate, evaluate_edge, position_tolerance_mm)
                    if (subdivision_evidence is None or
                            subdivision_evidence["maxBoundaryErrorMm"] > position_tolerance_mm or
                            subdivision_evidence["maxVertexErrorMm"] > position_tolerance_mm):
                        rejected.append(dict(score, rejectedBy="trim boundary coverage", sourceVertices=source_vertices,
                                             targetVertices=target_vertices, sourceEdgeCount=len(source_edges),
                                             targetEdgeCount=len(target_edges), boundaryCoverage=subdivision_evidence))
                        continue
                    boundary_error = subdivision_evidence["maxBoundaryErrorMm"]
                    vertex_error = subdivision_evidence["maxVertexErrorMm"]
                else:
                    vertex_error = max(
                        max(min(distance(p, q) for q in target_vertices) for p in source_vertices),
                        max(min(distance(p, q) for q in source_vertices) for p in target_vertices),
                    )
                if vertex_error > position_tolerance_mm:
                    rejected.append(dict(score, rejectedBy="exact trim vertices", maxVertexErrorMm=vertex_error))
                    continue
                used_edges, edge_errors = set(), []
                for edge in ([] if subdivision_evidence else source_edges):
                    edge_matches = []
                    for target_edge in target_edges:
                        error = max(distance(point, evaluate_edge(target_edge, point)) for point in edge["pointsMm"])
                        if error <= position_tolerance_mm:
                            edge_matches.append((target_edge, error))
                    if len(edge_matches) != 1 or edge_matches[0][0] in used_edges:
                        break
                    used_edges.add(edge_matches[0][0])
                    edge_errors.append(edge_matches[0][1])
                if not subdivision_evidence and len(edge_errors) != len(source_edges):
                    rejected.append(dict(score, rejectedBy="exact trimmed-edge curves"))
                    continue
                if not subdivision_evidence:
                    boundary_error = max(edge_errors)
            errors, dots = [], []
            for sample in source["samples"]:
                point, normal = evaluate(candidate["id"], sample["pointMm"])
                if len(point) != 3 or len(normal) != 3 or not all(map(finite, list(point) + list(normal))):
                    raise ValueError("Mechanical returned invalid surface evaluation data.")
                length = math.sqrt(sum(n * n for n in normal))
                if not length:
                    break
                errors.append(distance(point, sample["pointMm"]))
                dots.append(sum(a * b for a, b in zip(normal, sample["normal"])) / length)
            if len(errors) != len(source["samples"]) or max(errors) > position_tolerance_mm or min(dots) < 0.999:
                rejected.append(dict(score, rejectedBy="exact surface points/normals",
                                     maxSurfaceErrorMm=max(errors) if errors else None,
                                     minNormalDot=min(dots) if dots else None))
                continue
            matches.append(dict(score, maxSurfaceErrorMm=max(errors), minNormalDot=min(dots),
                                maxBoundaryErrorMm=boundary_error, maxVertexErrorMm=vertex_error,
                                 trimEdgesVerified=len(source["edges"]) if strict_trim else 0))
            if subdivision_evidence:
                matches[-1]["boundaryCoverage"] = subdivision_evidence
                matches[-1]["trimMatchingMethod"] = "bidirectional boundary union"
        if len(matches) != 1 or matches[0]["mechanicalFaceId"] in used:
            raise FaceMappingError(f"Face {source['key']} has {len(matches)} valid Mechanical matches; refusing ambiguous/missing mapping.",
                                   {"sourceFaceKey": source["key"], "validMatches": matches,
                                    "rejectedCandidates": sorted(rejected, key=lambda item: item["centroidErrorMm"])})
        match = matches[0]
        used.add(match["mechanicalFaceId"])
        mapping[source["key"]] = match["mechanicalFaceId"]
        evidence.append(match)
    return mapping, evidence


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
