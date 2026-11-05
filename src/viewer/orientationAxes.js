import * as THREE from 'three';

// A separate camera keeps the design axes legible at every zoom level. Its
// rotation matches the CAD camera; neither the model nor its coordinates move.
export class OrientationAxes {
  constructor() {
    this.scene = new THREE.Scene();
    this.camera = new THREE.OrthographicCamera(-1.65, 1.65, 1.65, -1.65, .1, 20);
    this.axes = [['X', [1, 0, 0], '#f27579'], ['Y', [0, 1, 0], '#79d794'], ['Z', [0, 0, 1], '#79afff']];
    for (const [name, vector, color] of this.axes) {
      const direction = new THREE.Vector3(...vector);
      const arrow = new THREE.ArrowHelper(direction, new THREE.Vector3(), 1, color, .2, .12);
      arrow.line.geometry = arrow.line.geometry.clone();
      arrow.cone.geometry = arrow.cone.geometry.clone();
      this.scene.add(arrow);
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 96;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#202630'; ctx.beginPath(); ctx.arc(48, 48, 43, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = color; ctx.lineWidth = 4; ctx.stroke();
      ctx.fillStyle = color; ctx.font = 'bold 54px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(name, 48, 50);
      const texture = new THREE.CanvasTexture(canvas);
      texture.colorSpace = THREE.SRGBColorSpace;
      const label = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture }));
      label.position.copy(direction).multiplyScalar(1.25); label.scale.setScalar(.47);
      this.scene.add(label);
    }
    this.scene.add(new THREE.Mesh(new THREE.SphereGeometry(.065, 12, 8), new THREE.MeshBasicMaterial({ color: '#dce3ed' })));
  }

  render(renderer, camera, container) {
    this.camera.quaternion.copy(camera.quaternion);
    this.camera.position.set(0, 0, 6).applyQuaternion(camera.quaternion);
    this.camera.updateMatrixWorld(true);
    const size = renderer.getSize(new THREE.Vector2());
    const side = Math.min(size.x < 450 ? 90 : 124, size.x, size.y);
    const inset = size.x < 450 ? 65 : 96;
    const viewport = renderer.getViewport(new THREE.Vector4());
    const autoClear = renderer.autoClear;
    renderer.autoClear = false;
    renderer.clearDepth();
    renderer.setViewport(Math.max(0, size.x - side - inset), 6, side, side);
    renderer.render(this.scene, this.camera);
    renderer.setViewport(viewport);
    renderer.autoClear = autoClear;
    // Expose the same projected axes to accessibility/browser verification.
    container.dataset.designAxes = JSON.stringify(this.axes.map(([name, vector]) => ({
      axis: name, screen: new THREE.Vector3(...vector).project(this.camera).toArray(),
    })));
  }

  dispose() {
    this.scene.traverse(object => {
      object.geometry?.dispose(); object.material?.map?.dispose(); object.material?.dispose();
    });
  }
}
