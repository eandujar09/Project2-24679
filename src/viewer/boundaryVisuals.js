import * as THREE from 'three';
import { conditionTypes } from '../boundaries/conditions.js';

// Sample triangle centroids, which lie on the tessellated face, rather than a
// bounding-box center that can be inside a solid or outside a trimmed face.
export function faceSamples(face, limit = 7) {
  const geometry = face.mesh.geometry;
  const triangles = [];
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  for (let triangle = face.first; triangle <= face.last; triangle++) {
    a.fromBufferAttribute(geometry.attributes.position, geometry.index.getX(triangle * 3));
    b.fromBufferAttribute(geometry.attributes.position, geometry.index.getX(triangle * 3 + 1));
    c.fromBufferAttribute(geometry.attributes.position, geometry.index.getX(triangle * 3 + 2));
    const cross = b.clone().sub(a).cross(c.clone().sub(a));
    const area = cross.length();
    if (area > 0) triangles.push({ point: a.clone().add(b).add(c).divideScalar(3), normal: cross.normalize(), area });
  }
  if (!triangles.length) return [];
  triangles.sort((a, b) => b.area - a.area);
  const chosen = [triangles[0]];
  // Farthest-point sampling avoids concentrating glyphs on neighboring triangles.
  const candidates = triangles.filter((_, i) => i % Math.max(1, Math.ceil(triangles.length / 200)) === 0);
  while (chosen.length < Math.min(limit, candidates.length)) {
    let best, distance = 0;
    for (const sample of candidates) {
      const nearest = Math.min(...chosen.map(other => sample.point.distanceToSquared(other.point)));
      if (nearest > distance) { best = sample; distance = nearest; }
    }
    if (!best) break;
    chosen.push(best);
  }
  return chosen;
}

export function createBoundaryVisual(condition, face, modelSize, { preview = false } = {}) {
  const group = new THREE.Group();
  group.userData.conditionId = condition.id;
  group.userData.preview = preview;
  const color = new THREE.Color(conditionTypes[condition.type].color);
  // Own compact face geometry: disposing a condition never frees model buffers.
  const positions = [];
  const source = face.mesh.geometry;
  const point = new THREE.Vector3();
  for (let i = face.first * 3; i < (face.last + 1) * 3; i++) {
    point.fromBufferAttribute(source.attributes.position, source.index.getX(i));
    positions.push(point.x, point.y, point.z);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  const overlay = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
    color, transparent: true, opacity: preview ? 0.14 : 0.26, side: THREE.DoubleSide,
    depthWrite: false, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1,
  }));
  overlay.renderOrder = 1;
  group.add(overlay);
  const samples = faceSamples(face, condition.type === 'pressure' ? 7 : condition.type === 'fixed' ? 4 : 1);
  const faceSize = face.box.getSize(new THREE.Vector3()).length();
  const size = Math.max(Math.min(faceSize * 0.22, modelSize * 0.1), modelSize * 0.015);
  for (const sample of samples) {
    const base = sample.point.clone().addScaledVector(sample.normal, size * 0.025);
    if (condition.type === 'fixed' || (condition.type === 'displacement' && Object.values(condition.values).every(value => value === 0))) {
      const normal = sample.normal;
      const tangent = new THREE.Vector3().crossVectors(normal, Math.abs(normal.z) < 0.9 ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(0, 1, 0)).normalize();
      const bitangent = normal.clone().cross(tangent);
      const top = base.clone().addScaledVector(normal, size * 0.55);
      const lines = [];
      for (let i = 0; i < 3; i++) {
        const foot = base.clone().addScaledVector(tangent, Math.cos(i * Math.PI * 2 / 3) * size * 0.4).addScaledVector(bitangent, Math.sin(i * Math.PI * 2 / 3) * size * 0.4);
        lines.push(...top.toArray(), ...foot.toArray());
        const end = foot.clone().addScaledVector(normal, -size * 0.16).addScaledVector(tangent, size * 0.13);
        lines.push(...foot.toArray(), ...end.toArray());
      }
      const support = new THREE.BufferGeometry();
      support.setAttribute('position', new THREE.Float32BufferAttribute(lines, 3));
      group.add(new THREE.LineSegments(support, new THREE.LineBasicMaterial({ color })));
    } else {
      let direction;
      let origin = base.clone();
      if (condition.type === 'pressure') {
        direction = sample.normal.clone().multiplyScalar(condition.values.magnitude > 0 ? -1 : 1);
        if (condition.values.magnitude > 0) origin.addScaledVector(sample.normal, size);
      } else {
        direction = new THREE.Vector3(condition.values.x, condition.values.y, condition.values.z);
        // Normalize without overflow even for very large finite components.
        direction.divideScalar(Math.max(Math.abs(direction.x), Math.abs(direction.y), Math.abs(direction.z))).normalize();
        origin.addScaledVector(sample.normal, size * 0.2);
        // An inward load must end at the face, rather than burying its arrowhead
        // inside the solid. Its direction remains the prescribed global vector.
        if (direction.dot(sample.normal) < 0) origin.copy(base).addScaledVector(direction, -size);
      }
      const arrow = new THREE.ArrowHelper(direction, origin, size, color, size * 0.28, size * 0.15);
      // ArrowHelper normally shares geometries globally; own them for disposal.
      arrow.line.geometry = arrow.line.geometry.clone();
      arrow.cone.geometry = arrow.cone.geometry.clone();
      group.add(arrow);
    }
  }
  group.userData.labelPoint = samples[0]?.point.clone();
  group.userData.labelPoints = samples.map(sample => sample.point.clone());
  return group;
}
