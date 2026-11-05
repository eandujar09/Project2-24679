import { Raycaster, Vector2 } from 'three';

export function setCameraView(scene, name) {
  if (!scene?.bounds || name === 'current') return;
  if (name === 'iso') { scene.camera.up.set(0, 0, 1); scene.fit(true); return; }
  const direction = { top: [0, 0, 1], bottom: [0, 0, -1], front: [0, -1, 0], back: [0, 1, 0], right: [1, 0, 0], left: [-1, 0, 0] }[name];
  if (!direction) throw new Error('Unknown camera view.');
  scene.camera.up.set(...(['top', 'bottom'].includes(name) ? [0, 1, 0] : [0, 0, 1]));
  scene.camera.position.copy(scene.controls.target).add({ x: direction[0], y: direction[1], z: direction[2] });
  scene.fit();
}

export function captureFrame(scene, modelId) {
  scene.updateFocus?.(true);
  scene.controls.update();
  scene.scene.updateMatrixWorld(true);
  scene.camera.updateMatrixWorld(true);
  scene.render();
  const source = scene.renderer.domElement;
  if (!source.width || !source.height) throw new Error('The viewport is not visible.');
  const scale = Math.min(1, 1200 / Math.max(source.width, source.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(source.width * scale));
  canvas.height = Math.max(1, Math.round(source.height * scale));
  canvas.getContext('2d').drawImage(source, 0, 0, canvas.width, canvas.height);
  return { modelId, width: canvas.width, height: canvas.height,
    camera: scene.camera.clone(), image: canvas.toDataURL('image/png') };
}

export function pickFrame(scene, frame, modelId, x, y) {
  if (!frame || frame.modelId !== modelId) throw new Error('The screenshot expired. Capture another view.');
  if (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || y < 0 || x >= frame.width || y >= frame.height) throw new Error('Point outside the screenshot.');
  const ray = new Raycaster();
  ray.setFromCamera(new Vector2(2 * x / frame.width - 1, 1 - 2 * y / frame.height), frame.camera);
  scene.scene.updateMatrixWorld(true);
  const hit = ray.intersectObjects(scene.meshes, false)[0];
  return hit ? hit.object.userData.triangleToFaceKey[hit.faceIndex] : null;
}
