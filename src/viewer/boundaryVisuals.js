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

function thermalGlyph(group, condition, base, normal, size, color) {
  const tangent = new THREE.Vector3().crossVectors(normal, Math.abs(normal.z) < .9 ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(0, 1, 0)).normalize();
  const across = normal.clone().cross(tangent);
  const point = (u, v, w = 0) => base.clone().addScaledVector(tangent, u * size).addScaledVector(normal, v * size).addScaledVector(across, w * size);
  const lines = [];
  const segment = (a, b) => lines.push(...a.toArray(), ...b.toArray());
  const arrow = (direction, origin) => {
    const glyph = new THREE.ArrowHelper(direction, origin, size, color, size * .25, size * .13);
    glyph.line.geometry = glyph.line.geometry.clone();
    glyph.cone.geometry = glyph.cone.geometry.clone();
    glyph.userData.thermalKind = condition.type;
    group.add(glyph);
  };
  if (condition.type === 'heat_flux' && condition.values.magnitude !== 0) {
    const inward = condition.values.magnitude > 0;
    arrow(normal.clone().multiplyScalar(inward ? -1 : 1), inward ? point(0, 1) : base.clone());
    return;
  }
  if (condition.type === 'temperature') {
    // Thermometer bulb/stem: a scalar temperature, not a force or flow direction.
    for (let i = 0; i < 24; i++) {
      const a = i * Math.PI / 12, b = (i + 1) * Math.PI / 12;
      segment(point(Math.cos(a) * .15, .2 + Math.sin(a) * .15), point(Math.cos(b) * .15, .2 + Math.sin(b) * .15));
    }
    segment(point(-.055, .34), point(-.055, 1));
    segment(point(.055, .34), point(.055, 1));
    segment(point(-.055, 1), point(.055, 1));
    for (let i = 0; i < 4; i++) segment(point(.055, .5 + i * .12), point(.2, .5 + i * .12));
  } else if (condition.type === 'convection' || condition.type === 'radiation') {
    // Wavy exchange rays deliberately have no arrowheads: net direction is unknown.
    const count = condition.type === 'radiation' ? 3 : 2;
    for (let ray = 0; ray < count; ray++) {
      const offset = (ray - (count - 1) / 2) * .35;
      const wave = t => point(offset + .07 * Math.sin(t * Math.PI * 5), .15 + t * .85, condition.type === 'radiation' ? offset * t * .7 : 0);
      for (let i = 0; i < 20; i++) segment(wave(i / 20), wave((i + 1) / 20));
    }
    if (condition.type === 'convection') {
      // Film boundary marker distinguishes convection from radiative exchange.
      segment(point(-.6, .08), point(.6, .08));
      segment(point(-.6, .18), point(.6, .18));
    }
  } else {
    // Insulation barrier (also used for an explicitly zero heat flux).
    segment(point(-.6, .12), point(.6, .12));
    segment(point(-.6, .28), point(.6, .28));
    for (let i = -2; i <= 2; i++) segment(point(i * .22, .28), point(i * .22 - .15, .48));
    segment(point(-.2, .55), point(.2, .95));
    segment(point(.2, .55), point(-.2, .95));
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(lines, 3));
  const strokes = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color }));
  strokes.userData.thermalKind = condition.type;
  group.add(strokes);
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
  const thermal = ['temperature', 'heat_flux', 'convection', 'radiation', 'adiabatic'].includes(condition.type);
  const samples = faceSamples(face, ['pressure', 'pressure_outlet', 'velocity_inlet', 'heat_flux'].includes(condition.type) ? 7 : ['fixed', 'wall', 'symmetry'].includes(condition.type) || thermal ? 4 : 1);
  const faceSize = face.box.getSize(new THREE.Vector3()).length();
  const size = Math.max(Math.min(faceSize * 0.22, modelSize * 0.1), modelSize * 0.015);
  for (const sample of samples) {
    const base = sample.point.clone().addScaledVector(sample.normal, size * 0.025);
    if (thermal) {
      thermalGlyph(group, condition, base, sample.normal, size, color);
    } else if (condition.type === 'wall' || condition.type === 'symmetry') {
      // Wall hatching and paired tangent strokes distinguish CFD from structural supports.
      const tangent = new THREE.Vector3().crossVectors(sample.normal, Math.abs(sample.normal.z) < 0.9 ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(0, 1, 0)).normalize();
      const across = sample.normal.clone().cross(tangent);
      const lines = [];
      for (let i = -1; i <= 1; i++) {
        const center = base.clone().addScaledVector(across, i * size * 0.25);
        const a = center.clone().addScaledVector(tangent, -size * 0.45);
        const b = center.clone().addScaledVector(tangent, size * 0.45);
        lines.push(...a.toArray(), ...b.toArray());
        if (condition.type === 'wall') lines.push(...a.toArray(), ...a.clone().addScaledVector(across, -size * 0.2).addScaledVector(tangent, -size * 0.15).toArray());
      }
      const strokes = new THREE.BufferGeometry();
      strokes.setAttribute('position', new THREE.Float32BufferAttribute(lines, 3));
      group.add(new THREE.LineSegments(strokes, new THREE.LineBasicMaterial({ color })));
    } else if (condition.type === 'fixed' || (condition.type === 'displacement' && Object.values(condition.values).every(value => value === 0))) {
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
      if (condition.type === 'pressure_outlet') {
        // Outlet glyph denotes outward flow, NOT the sign of gauge pressure.
        direction = sample.normal.clone();
      } else if (condition.type === 'pressure') {
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
