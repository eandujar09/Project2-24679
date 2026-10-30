// occt-import-js 0.0.23 uses inclusive triangle ranges, not vertex offsets.
export function buildFaceMap(mesh, componentKey, identities = null) {
  const count = mesh.index.array.length / 3;
  if (!Number.isInteger(count)) throw new Error('Invalid triangle indices in imported mesh.');
  const triangleToFaceKey = new Array(count);
  const faces = [];
  if (!mesh.brep_faces?.length) throw new Error('The importer returned no CAD face metadata.');
  if (identities && (!Array.isArray(identities) || identities.length !== mesh.brep_faces.length ||
      identities.some(face => !face || typeof face.key !== 'string' || !face.key.trim() || !Number.isInteger(face.index)) ||
      new Set(identities.map(face => face.key)).size !== identities.length)) {
    throw new Error('Invalid external CAD face identities.');
  }
  mesh.brep_faces.forEach((face, faceIndex) => {
    const { first, last } = face;
    // Empty, untessellated faces can be represented by an inverted range.
    if (last < first) return;
    if (!Number.isInteger(first) || !Number.isInteger(last) || first < 0 || last >= count) {
      throw new Error('The importer returned an invalid CAD face triangle range.');
    }
    const key = identities ? identities[faceIndex].key : `${componentKey}:face:${faceIndex}`;
    for (let i = first; i <= last; i++) {
      if (triangleToFaceKey[i]) throw new Error('Overlapping CAD face ranges.');
      triangleToFaceKey[i] = key;
    }
    faces.push({ key, first, last, faceIndex: identities ? identities[faceIndex].index : faceIndex, color: face.color });
  });
  if (triangleToFaceKey.includes(undefined)) throw new Error('Some triangles have no original CAD face mapping.');
  return { triangleToFaceKey, faces };
}

export function meshOccurrences(result) {
  const occurrences = [];
  function visit(node, path) {
    (node.meshes || []).forEach((index, slot) => {
      if (!result.meshes[index]) throw new Error('Invalid component mesh reference.');
      occurrences.push({ mesh: result.meshes[index], componentKey: `${path}:mesh:${index}:slot:${slot}`, name: node.name });
    });
    (node.children || []).forEach((child, i) => visit(child, `${path}.${i}`));
  }
  if (result.root) visit(result.root, 'occurrence-0');
  if (!occurrences.length) throw new Error('No renderable components found in this STEP file.');
  return occurrences;
}
