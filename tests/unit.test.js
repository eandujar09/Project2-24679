import test from 'node:test';
import assert from 'node:assert/strict';
import { buildFaceMap, meshOccurrences } from '../src/cad/faceMap.js';
import { validateAnnotations, validateProjectAnnotations } from '../src/comments/exportImport.js';
import { validateConditions } from '../src/boundaries/conditions.js';
import { createBoundaryVisual, faceSamples } from '../src/viewer/boundaryVisuals.js';
import * as THREE from 'three';
import { pickFrame } from '../src/studio/visual.js';

test('image pixels pick exact faces using the frozen camera after the live view moves', () => {
  const scene = new THREE.Scene();
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), new THREE.MeshBasicMaterial({ side: THREE.DoubleSide }));
  mesh.userData.triangleToFaceKey = ['right', 'right', 'left', 'left', 'top', 'top', 'bottom', 'bottom', 'front', 'front', 'back', 'back'];
  scene.add(mesh); scene.updateMatrixWorld(true);
  const camera = new THREE.PerspectiveCamera(60, 2, .1, 100);
  camera.position.set(0, 0, 5); camera.lookAt(0, 0, 0); camera.updateMatrixWorld(true);
  const frame = { modelId: 'cad', camera: camera.clone(), width: 600, height: 300 };
  camera.position.set(5, 0, 0); camera.lookAt(0, 0, 0); camera.updateMatrixWorld(true);
  const viewer = { scene, meshes: [mesh], camera };
  assert.equal(pickFrame(viewer, frame, 'cad', 300, 150), 'front');
  const p = new THREE.Vector3(.4, .3, 1).project(frame.camera);
  assert.equal(pickFrame(viewer, frame, 'cad', (p.x + 1) * 300, (1 - p.y) * 150), 'front');
  assert.equal(pickFrame(viewer, frame, 'cad', 0, 0), null);
  assert.throws(() => pickFrame(viewer, frame, 'other-cad', 300, 150), /expired/);
  assert.throws(() => pickFrame(viewer, frame, 'cad', 600, 150), /outside/);
  mesh.geometry.dispose(); mesh.material.dispose();
});

test('face ranges include both endpoints and group many triangles into one face', () => {
  const mesh = { index: { array: new Array(300).fill(0) }, brep_faces: [{ first: 0, last: 79 }, { first: 80, last: 99 }] };
  const { triangleToFaceKey: map, faces } = buildFaceMap(mesh, 'part');
  assert.equal(faces.length, 2);
  assert.equal(map[0], map[79]);
  assert.notEqual(map[79], map[80]);
  assert.equal(map[80], map[99]);
  assert.equal(map.filter(key => key === faces[0].key).length, 80);
});

test('missing, overlapping, and out-of-bounds mappings are rejected', () => {
  for (const ranges of [[], [{ first: 0, last: 0 }], [{ first: 0, last: 2 }], [{ first: 0, last: 1 }, { first: 1, last: 1 }]]) {
    assert.throws(() => buildFaceMap({ index: { array: [0, 1, 2, 2, 3, 0] }, brep_faces: ranges }, 'part'));
  }
});

test('Python identities remain authoritative over complete CAD face triangle ranges', () => {
  const mesh = { index: { array: new Array(18).fill(0) }, brep_faces: [{ first: 0, last: 3 }, { first: 4, last: 5 }] };
  const identities = [{ key: 'python-ocp-v1:face:1', index: 1 }, { key: 'python-ocp-v1:face:2', index: 2 }];
  const mapping = buildFaceMap(mesh, 'occurrence', identities);
  assert.deepEqual(mapping.triangleToFaceKey, [identities[0].key, identities[0].key, identities[0].key, identities[0].key, identities[1].key, identities[1].key]);
  assert.equal(mapping.faces[0].faceIndex, 1);
  for (const invalid of [[], [identities[0]], [identities[0], identities[0]], [{ key: '', index: 1 }, identities[1]]]) {
    assert.throws(() => buildFaceMap(mesh, 'occurrence', invalid), /identities/);
  }
});

test('repeated geometry and repeated names have distinct occurrence face keys', () => {
  const mesh = { index: { array: [0, 1, 2] }, brep_faces: [{ first: 0, last: 0 }] };
  const node = { name: 'identical name', meshes: [0], children: [] };
  const result = { meshes: [mesh], root: { meshes: [], children: [node, node] } };
  const keys = meshOccurrences(result).map(item => buildFaceMap(item.mesh, item.componentKey).faces[0].key);
  assert.equal(new Set(keys).size, 2);
});

const comment = { id: 'unique-id', modelId: 'hash', faceKey: 'part:face:0', text: '  Surface check  ', createdAt: '2026-10-26T10:00:00Z', updatedAt: '2026-10-26T10:00:00Z' };
const annotations = comments => ({ schemaVersion: 1, modelId: 'hash', filename: 'part.step', comments });

test('annotation validation preserves model association and trims text', () => {
  const validated = validateAnnotations(annotations([comment]), 'hash');
  assert.equal(validated[0].text, 'Surface check');
  assert.equal(validated[0].faceKey, comment.faceKey);
  assert.throws(() => validateAnnotations(annotations([comment]), 'different-hash'), /mismatch/);
});

test('annotation validation rejects invalid records atomically', () => {
  for (const update of [{ text: ' ' }, { modelId: 'other' }, { faceKey: null }, { updatedAt: 'invalid' }, { anchor: [1, 2, Infinity] }]) {
    assert.throws(() => validateAnnotations(annotations([comment, { ...comment, id: 'second', ...update }]), 'hash'));
  }
  assert.throws(() => validateAnnotations(annotations([comment, comment]), 'hash'));
  assert.throws(() => validateAnnotations({ ...annotations([]), schemaVersion: 2 }, 'hash'));
});

const boundary = { id: 'bc-1', modelId: 'hash', faceKey: 'part:face:0', type: 'force', values: { x: -10, y: 0, z: 20 }, createdAt: comment.createdAt, updatedAt: comment.updatedAt };

test('boundary validation rejects invalid physics fields and cross-model identity', () => {
  assert.deepEqual(validateConditions([boundary], 'hash')[0].values, boundary.values);
  for (const update of [{ type: 'unknown' }, { modelId: 'other' }, { values: { x: 0, y: 0, z: 0 } }, { values: { x: '10', y: 0, z: 1 } }, { values: { x: NaN, y: 0, z: 1 } }, { type: 'pressure', values: { magnitude: 0 } }, { type: 'pressure', values: { magnitude: Infinity } }]) {
    assert.throws(() => validateConditions([{ ...boundary, ...update }], 'hash'));
  }
  assert.throws(() => validateConditions([boundary, boundary], 'hash'));
  assert.equal(validateConditions([{ ...boundary, type: 'displacement', values: { x: 0, y: 0, z: 0 } }], 'hash').length, 1);
});

test('schema 2 transfers conditions, schema 1 remains compatible, invalid conditions reject the project', () => {
  const data = { ...annotations([comment]), schemaVersion: 2, boundaryConditions: [boundary] };
  assert.equal(validateProjectAnnotations(data, 'hash').boundaryConditions[0].values.x, -10);
  assert.deepEqual(validateProjectAnnotations(annotations([comment]), 'hash').boundaryConditions, []);
  assert.throws(() => validateProjectAnnotations({ ...data, boundaryConditions: [{ ...boundary, values: {} }] }, 'hash'));
});

function flatFace() {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0], 3));
  geometry.setIndex([0, 1, 2, 0, 2, 3]);
  return { mesh: new THREE.Mesh(geometry), first: 0, last: 1, box: new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(1, 1, 0)) };
}

test('visuals cover the complete face with owned buffers and arrows follow global force direction', () => {
  const face = flatFace();
  const visual = createBoundaryVisual(boundary, face, 2);
  assert.equal(visual.children[0].geometry.attributes.position.count, 6);
  assert.notEqual(visual.children[0].geometry.attributes.position, face.mesh.geometry.attributes.position);
  const arrow = visual.children.find(child => child.type === 'ArrowHelper');
  const direction = new THREE.Vector3(0, 1, 0).applyQuaternion(arrow.quaternion);
  assert.ok(direction.distanceTo(new THREE.Vector3(-10, 0, 20).normalize()) < 1e-8);
  const inward = createBoundaryVisual({ ...boundary, values: { x: 0, y: 0, z: -1 } }, face, 2);
  const inwardArrow = inward.children.find(child => child.type === 'ArrowHelper');
  const arrowTip = inwardArrow.position.clone().addScaledVector(new THREE.Vector3(0, 1, 0).applyQuaternion(inwardArrow.quaternion), inwardArrow.line.scale.y + inwardArrow.cone.scale.y);
  assert.ok(inwardArrow.position.z > 0);
  assert.ok(arrowTip.z >= -1e-8);
  for (const sample of faceSamples(face)) {
    assert.equal(sample.point.z, 0);
    assert.ok(sample.point.x >= 0 && sample.point.x <= 1 && sample.point.y >= 0 && sample.point.y <= 1);
  }
});

test('pressure arrows follow local normals and reverse with pressure sign; supports have visible glyphs', () => {
  const face = flatFace();
  for (const magnitude of [2, -2]) {
    const visual = createBoundaryVisual({ ...boundary, type: 'pressure', values: { magnitude } }, face, 2);
    const arrows = visual.children.filter(child => child.type === 'ArrowHelper');
    assert.ok(arrows.length > 1);
    for (const arrow of arrows) {
      const direction = new THREE.Vector3(0, 1, 0).applyQuaternion(arrow.quaternion);
      assert.ok(Math.abs(direction.z - (magnitude > 0 ? -1 : 1)) < 1e-8);
    }
  }
  const support = createBoundaryVisual({ ...boundary, type: 'fixed', values: {} }, face, 2);
  assert.ok(support.children.some(child => child.isLineSegments));
});
