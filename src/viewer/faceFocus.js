import * as THREE from 'three';
import { faceSamples } from './boundaryVisuals.js';

// A bounding-box center alone cannot tell which side of a plate or hole wall
// the user needs to see. Derive the view from the actual face and occlusion.
export function faceFocusPose(face, bounds, camera, currentTarget, meshes) {
  if (!face || !bounds || bounds.isEmpty()) return null;
  const samples = faceSamples(face, 16);
  if (!samples.length) return null;
  const center = face.box.getCenter(new THREE.Vector3());
  const modelSize = bounds.getSize(new THREE.Vector3()).length() || 1;
  // Keep surrounding geometry visible when proposing a small hole wall or tip.
  const size = Math.max(face.box.getSize(new THREE.Vector3()).length(), modelSize * 0.4);
  const fitDistance = size / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)))
    * 1.3 / Math.min(Math.max(camera.aspect, 0.1), 1);
  const current = camera.position.clone().sub(currentTarget).normalize();
  if (!current.lengthSq()) current.set(1, -1.4, 0.9).normalize();
  const mean = samples.reduce((sum, sample) => sum.addScaledVector(sample.normal, sample.area), new THREE.Vector3());
  const area = samples.reduce((sum, sample) => sum + sample.area, 0);
  const planar = mean.length() / area > 0.99;
  const directions = [current];
  if (mean.length() > area * 0.01) directions.push(mean.normalize());
  directions.push(...samples.map(sample => sample.normal),
    ...[[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]].map(v => new THREE.Vector3(...v)));
  const unique = directions.filter((direction, i) => !directions.slice(0, i).some(other => other.dot(direction) > 0.9999));
  const ray = new THREE.Raycaster();
  const tolerance = modelSize * 0.0001;
  let best;
  for (const direction of unique) {
    // Keep the camera outside the model bounds, including for concave faces.
    let exit = Infinity;
    for (const axis of ['x', 'y', 'z']) {
      if (Math.abs(direction[axis]) < 1e-8) continue;
      const boundary = direction[axis] > 0 ? bounds.max[axis] : bounds.min[axis];
      exit = Math.min(exit, (boundary - center[axis]) / direction[axis]);
    }
    const distance = Math.max(fitDistance, exit + modelSize * 0.08);
    const position = center.clone().addScaledVector(direction, distance);
    let visibleArea = 0;
    for (const sample of samples) {
      const toPoint = sample.point.clone().sub(position);
      const length = toPoint.length();
      ray.set(position, toPoint.normalize());
      const hit = ray.intersectObjects(meshes, false)[0];
      if (!hit || hit.distance >= length - tolerance) visibleArea += sample.area;
    }
    // Planes face the camera. Curved faces use a clear angle near the current
    // one; cancelling normals must not produce an invalid camera direction.
    const score = visibleArea / area * 10 + (planar ? mean.dot(direction) * 0.5 : 0) + current.dot(direction) * 0.1;
    if (!best || score > best.score) best = { position, target: center, direction, score };
  }
  const up = Math.abs(best.direction.z) > 0.95 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(0, 0, 1);
  return { position: best.position, target: center, up };
}
