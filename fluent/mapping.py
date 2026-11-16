"""Fail-closed, sampled geometric correspondence; zone names are never identities."""
import numpy as np
import trimesh


def triangulate(vertices, connectivity):
    vertices = np.asarray(vertices, dtype=float).reshape((-1, 3))
    flat = np.asarray(connectivity, dtype=int).ravel()
    faces, i = [], 0
    while i < len(flat):
        count = int(flat[i]); i += 1
        indices = flat[i:i + count]; i += count
        if count < 3 or len(indices) != count or np.any(indices < 0) or np.any(indices >= len(vertices)):
            raise ValueError('Invalid Fluent face connectivity.')
        faces.extend([int(indices[0]), int(indices[j]), int(indices[j + 1])] for j in range(1, count - 1))
    if not faces or not np.isfinite(vertices).all():
        raise ValueError('Fluent returned an empty or nonfinite boundary surface.')
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def distance_to_mesh(mesh, points):
    # Bounded batches avoid the huge point x triangle allocation of the naive API.
    distances = []
    for start in range(0, len(points), 8):
        _, d, _ = trimesh.proximity.closest_point_naive(mesh, np.asarray(points[start:start + 8]))
        distances.extend(d)
    return max(distances, default=float('inf'))


def match_zones(signatures, zones, exact_distance, tolerance_mm):
    """Check all zone vertices/triangle centers against the trimmed original face.

    Reverse interior/trim samples plus area reject partial/split/merged surfaces.
    This finite sampling is evidence, not a proof of topology or mesh quality.
    exact_distance(face_key, points_mm) is supplied by the OpenCascade adapter.
    """
    if len(signatures) != len(zones):
        raise ValueError('Fluent merged or split CAD faces. Preserve separate face zones; numeric-order mapping is forbidden.')
    mapping, evidence, used = {}, [], set()
    for face in signatures:
        matches = []
        for name, mesh in zones.items():
            area_error = abs(mesh.area - face['areaMm2']) / face['areaMm2']
            if area_error > 0.02:
                continue
            points = np.vstack((mesh.vertices, mesh.triangles_center))
            forward = exact_distance(face['key'], points)
            if forward > tolerance_mm:
                continue
            source_points = [s['pointMm'] for s in face['samples']]
            source_points += face['verticesMm']
            source_points += [p for edge in face['edges'] for p in edge['pointsMm']]
            reverse = distance_to_mesh(mesh, source_points)
            if reverse <= tolerance_mm:
                matches.append((name, {'faceKey': face['key'], 'zone': name,
                                       'relativeAreaError': float(area_error),
                                       'forwardErrorMm': float(forward), 'reverseErrorMm': float(reverse),
                                       'toleranceMm': tolerance_mm}))
        if len(matches) != 1 or matches[0][0] in used:
            raise ValueError('No unique Fluent boundary mapping for ' + face['key'] + '; refine/preserve face zones rather than guessing.')
        name, row = matches[0]
        mapping[face['key']] = name
        used.add(name); evidence.append(row)
    return mapping, evidence
