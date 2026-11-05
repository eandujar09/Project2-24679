import * as THREE from 'three';

export function gravitySummary(load) {
  const prefix = { proposed: 'Proposed gravity', running: 'Running · Gravity', applied: 'Gravity' }[load.state] || 'Gravity';
  if (!validGravity(load)) return `${prefix} · direction needs review`;
  const magnitude = Math.hypot(...load.vector);
  const axis = load.vector.findIndex(x => Math.abs(x) > magnitude * .999999);
  const direction = axis < 0 ? load.vector.map(x => Number(x.toPrecision(4))).join(', ') : `${load.vector[axis] < 0 ? '−' : '+'}${'XYZ'[axis]}`;
  return `${prefix} · ${direction} · ${Number(magnitude.toPrecision(5))} m/s²`;
}

export function validGravity(load) {
  return Array.isArray(load?.vector) && load.vector.length === 3 && load.vector.every(Number.isFinite)
    && Number.isFinite(Math.hypot(...load.vector)) && Math.hypot(...load.vector) > 0;
}

export function createGravityVisual(load, bounds, index = 0) {
  if (!validGravity(load) || !bounds || bounds.isEmpty()) return null;
  const size = bounds.getSize(new THREE.Vector3()).length() || 1;
  const direction = new THREE.Vector3(...load.vector).normalize();
  const length = size * .28;
  // Whole-body gravity sits outside the part, never on a selected CAD face.
  const origin = bounds.getCenter(new THREE.Vector3());
  origin.x = bounds.max.x + size * (.1 + index * .085);
  origin.addScaledVector(direction, -length / 2);
  const group = new THREE.Group();
  group.position.copy(origin);
  group.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction);
  const material = new THREE.MeshBasicMaterial({ color: load.state === 'proposed' ? '#c6a4ff' : '#f2c85b',
    transparent: true, opacity: load.state === 'proposed' ? .65 : 1, depthTest: false, depthWrite: false });
  const shaft = new THREE.Mesh(new THREE.CylinderGeometry(size * .0035, size * .0035, length * .76, 12), material);
  shaft.position.y = length * .38;
  const head = new THREE.Mesh(new THREE.ConeGeometry(size * .019, length * .24, 16), material.clone());
  head.position.y = length * .88;
  group.add(shaft, head);
  group.traverse(object => { object.renderOrder = 5; });
  group.userData.labelPoints = [origin.clone()];
  group.userData.direction = direction.toArray();
  return group;
}
