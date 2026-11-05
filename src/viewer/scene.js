import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { buildFaceMap, meshOccurrences } from '../cad/faceMap.js';
import { createBoundaryVisual } from './boundaryVisuals.js';
import { conditionTypes, conditionSummary } from '../boundaries/conditions.js';
import { faceFocusPose } from './faceFocus.js';
import { OrientationAxes } from './orientationAxes.js';
import { createGravityVisual, gravitySummary } from './gravityVisuals.js';

export class Viewer {
  constructor(container, onSelect) {
    this.container = container;
    this.onSelect = onSelect;
    this.faces = new Map();
    this.meshes = [];
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color('#111d2c');
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.01, 100000);
    this.camera.up.set(0, 0, 1);
    this.orientationAxes = new OrientationAxes();
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.domElement.setAttribute('aria-label', '3D CAD viewport with design axes: X red, Y green, Z blue. Drag to orbit, right drag to pan, scroll to zoom. Use the face list to select faces with a keyboard.');
    this.renderer.domElement.tabIndex = 0;
    container.prepend(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.addEventListener('start', () => this.cancelFocus());
    this.scene.add(new THREE.HemisphereLight(0xe4f5ff, 0x46516a, 2.5));
    const light = new THREE.DirectionalLight(0xffffff, 3);
    light.position.set(3, -4, 7);
    this.scene.add(light);
    this.group = new THREE.Group();
    this.scene.add(this.group);
    this.boundaryGroup = new THREE.Group();
    this.scene.add(this.boundaryGroup);
    this.boundaryLabels = document.createElement('div');
    this.boundaryLabels.className = 'boundary-labels';
    container.append(this.boundaryLabels);
    this.boundaryLabelEntries = [];
    this.gravityGroup = new THREE.Group();
    this.scene.add(this.gravityGroup);
    this.gravityLabels = document.createElement('div');
    this.gravityLabels.className = 'boundary-labels gravity-labels';
    container.append(this.gravityLabels);
    this.gravityLabelEntries = [];
    this.boundaryRaycaster = new THREE.Raycaster();
    this.hoverOverlay = this.createOverlay(0x72e3d0, 0.36);
    this.selectedOverlay = this.createOverlay(0xffc76a, 0.6);
    this.assistantOverlays = [];
    this.assistantKeys = [];
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    const canvas = this.renderer.domElement;
    canvas.addEventListener('pointerdown', e => { this.down = { x: e.clientX, y: e.clientY, button: e.button, moved: false }; });
    canvas.addEventListener('pointermove', e => {
      if (this.down && Math.hypot(e.clientX - this.down.x, e.clientY - this.down.y) >= 5) this.down.moved = true;
      if (e.buttons) { this.hover(null); return; }
      this.hover(this.pick(e)?.key || null);
    });
    canvas.addEventListener('pointerleave', () => this.hover(null));
    canvas.addEventListener('pointerup', e => {
      if (this.down?.button === 0 && !this.down.moved && Math.hypot(e.clientX - this.down.x, e.clientY - this.down.y) < 5) {
        const hit = this.pick(e);
        this.onSelect(hit?.key || null, hit?.point.toArray());
      }
      this.down = null;
    });
    canvas.addEventListener('pointercancel', () => { this.down = null; });
    canvas.addEventListener('webglcontextlost', e => {
      e.preventDefault();
      container.dispatchEvent(new CustomEvent('viewer-error', { detail: 'The graphics context was lost. Reload the page to restore the viewer.' }));
    });
    this.resize = new ResizeObserver(() => {
      const { width, height } = container.getBoundingClientRect();
      this.renderer.setSize(width, height);
      this.camera.aspect = width / Math.max(height, 1);
      this.camera.updateProjectionMatrix();
      this.labelsDirty = true;
    });
    this.resize.observe(container);
    this.renderer.setAnimationLoop(() => {
      this.updateFocus();
      this.controls.update();
      this.updateClipping();
      this.render();
      this.positionBoundaryLabels();
    });
  }

  render() {
    this.renderer.render(this.scene, this.camera);
    this.orientationAxes.render(this.renderer, this.camera, this.container);
  }

  createOverlay(color, opacity) {
    const mesh = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({
      color, transparent: true, opacity, side: THREE.DoubleSide,
      depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
    }));
    mesh.visible = false;
    mesh.renderOrder = 2;
    this.scene.add(mesh);
    return mesh;
  }

  load(result, { faceIdentities } = {}) {
    const group = new THREE.Group();
    const faces = new Map();
    const meshes = [];
    try {
      for (const occurrence of meshOccurrences(result)) {
        const source = occurrence.mesh;
        const map = buildFaceMap(source, occurrence.componentKey, faceIdentities?.[occurrence.componentKey]);
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(source.attributes.position.array, 3));
        if (source.attributes.normal?.array?.length) geometry.setAttribute('normal', new THREE.Float32BufferAttribute(source.attributes.normal.array, 3));
        geometry.setIndex(source.index.array);
        if (!geometry.hasAttribute('normal')) geometry.computeVertexNormals();
        geometry.computeBoundingBox();
        geometry.computeBoundingSphere();
        const material = new THREE.MeshStandardMaterial({ color: source.color ? new THREE.Color(...source.color) : new THREE.Color('#91acbf'), metalness: 0.22, roughness: 0.55, side: THREE.DoubleSide });
        const mesh = new THREE.Mesh(geometry, material);
        mesh.userData = map;
        group.add(mesh);
        meshes.push(mesh);
        for (const face of map.faces) {
          if (faces.has(face.key)) throw new Error('Duplicate CAD face identity across meshes.');
          const box = new THREE.Box3();
          const point = new THREE.Vector3();
          for (let i = face.first * 3; i < (face.last + 1) * 3; i++) {
            point.fromBufferAttribute(geometry.attributes.position, geometry.index.getX(i));
            box.expandByPoint(point);
          }
          faces.set(face.key, { ...face, mesh, box, name: occurrence.name || source.name || 'Component' });
        }
      }
    } catch (error) {
      this.disposeGroup(group);
      throw error;
    }
    this.select(null);
    this.hover(null);
    this.highlight([]);
    this.setBoundaryConditions([]);
    this.setGravity([]);
    // Overlay buffers are shared with model meshes. Release their binding state
    // only when replacing the model, never on a hover/selection transition.
    for (const overlay of [this.hoverOverlay, this.selectedOverlay]) {
      overlay.geometry.dispose();
      overlay.geometry = new THREE.BufferGeometry();
    }
    this.disposeGroup(this.group);
    this.scene.remove(this.group);
    this.group = group;
    this.scene.add(group);
    this.faces = faces;
    this.meshes = meshes;
    this.bounds = new THREE.Box3().setFromObject(group);
    this.boundingSphere = this.bounds.getBoundingSphere(new THREE.Sphere());
    this.fit(true);
  }

  disposeGroup(group) {
    group.traverse(object => { object.geometry?.dispose(); object.material?.dispose(); });
  }

  overlay(mesh, key) {
    mesh.visible = false;
    const face = this.faces.get(key);
    if (!face) return;
    mesh.geometry.setAttribute('position', face.mesh.geometry.attributes.position);
    mesh.geometry.setIndex(face.mesh.geometry.index);
    mesh.geometry.setDrawRange(face.first * 3, (face.last - face.first + 1) * 3);
    mesh.geometry.boundingSphere = face.mesh.geometry.boundingSphere;
    mesh.visible = true;
  }

  hover(key) {
    if (key === this.hovered) return;
    this.hovered = key;
    this.overlay(this.hoverOverlay, key === this.selected ? null : key);
    this.renderer.domElement.style.cursor = key ? 'pointer' : 'grab';
  }

  select(key) {
    this.selected = key;
    this.overlay(this.selectedOverlay, key);
    this.overlay(this.hoverOverlay, this.hovered === key ? null : this.hovered);
    this.assistantOverlays.forEach((overlay, index) => this.overlay(overlay, this.assistantKeys[index] === key ? null : this.assistantKeys[index]));
    for (const entry of this.boundaryLabelEntries) entry.element.classList.toggle('selected', entry.faceKey === key);
  }

  highlight(keys) {
    const unique = [...new Set(keys)].filter(key => this.faces.has(key));
    if (JSON.stringify(unique) === JSON.stringify(this.assistantKeys)) return;
    this.assistantOverlays.forEach(mesh => {
      this.scene.remove(mesh);
      mesh.geometry.dispose();
      mesh.material.dispose();
    });
    this.assistantKeys = unique;
    this.assistantOverlays = unique.map(key => {
      const mesh = this.createOverlay(0xa78bfa, 0.48);
      mesh.renderOrder = 1;
      this.overlay(mesh, key === this.selected ? null : key);
      return mesh;
    });
  }

  setBoundaryConditions(conditions, proposals = []) {
    this.disposeGroup(this.boundaryGroup);
    this.boundaryGroup.clear();
    this.boundaryLabels.replaceChildren();
    this.boundaryLabelEntries = [];
    if (!this.bounds) return;
    const modelSize = this.bounds.getSize(new THREE.Vector3()).length() || 1;
    // An edit previews its replacement without duplicating the old arrow. The
    // saved condition remains untouched and returns if the proposal is dismissed.
    const replaced = new Set(proposals.map(condition => condition.replacesId).filter(Boolean));
    const displayed = [...conditions.filter(condition => !replaced.has(condition.id)).map(condition => ({ condition, preview: false })),
      ...proposals.map(condition => ({ condition, preview: true }))];
    for (const { condition, preview } of displayed) {
      const face = this.faces.get(condition.faceKey);
      if (!face) continue;
      const visual = createBoundaryVisual(condition, face, modelSize, { preview });
      this.boundaryGroup.add(visual);
      if (!visual.userData.labelPoint) continue;
      const element = document.createElement('div');
      element.className = 'boundary-label';
      element.classList.toggle('proposed', preview);
      element.dataset.conditionState = preview ? 'proposed' : 'applied';
      element.dataset.conditionId = condition.id;
      element.style.setProperty('--condition-color', conditionTypes[condition.type].color);
      element.textContent = `${preview ? 'Proposed · ' : ''}${conditionTypes[condition.type].label} · ${conditionSummary(condition)}`;
      element.classList.toggle('selected', condition.faceKey === this.selected);
      this.boundaryLabels.append(element);
      this.boundaryLabelEntries.push({ element, points: visual.userData.labelPoints, faceKey: condition.faceKey });
    }
    this.labelsDirty = true;
  }

  setGravity(loads = []) {
    this.disposeGroup(this.gravityGroup);
    this.gravityGroup.clear();
    this.gravityLabels.replaceChildren();
    this.gravityLabelEntries = [];
    for (const [index, load] of loads.entries()) {
      const visual = createGravityVisual(load, this.bounds, index);
      if (!visual) continue;
      this.gravityGroup.add(visual);
      const element = document.createElement('div');
      element.className = 'boundary-label gravity-label';
      element.classList.toggle('proposed', load.state === 'proposed');
      element.dataset.conditionState = load.state;
      element.dataset.gravityVector = JSON.stringify(load.vector);
      element.style.setProperty('--condition-color', load.state === 'proposed' ? '#c6a4ff' : '#f2c85b');
      element.textContent = gravitySummary(load);
      this.gravityLabels.append(element);
      this.gravityLabelEntries.push({ element, points: visual.userData.labelPoints, faceKey: load.id, alwaysVisible: true });
    }
    this.labelsDirty = true;
  }

  positionBoundaryLabels() {
    const entries = [...this.boundaryLabelEntries, ...this.gravityLabelEntries];
    if (!entries.length) return;
    const matrix = new THREE.Matrix4().multiplyMatrices(this.camera.projectionMatrix, this.camera.matrixWorldInverse);
    if (!this.labelsDirty && this.labelCameraMatrix?.equals(matrix)) return;
    this.labelCameraMatrix = matrix;
    this.labelsDirty = false;
    const width = this.renderer.domElement.clientWidth;
    const height = this.renderer.domElement.clientHeight;
    const tolerance = (this.bounds?.getSize(new THREE.Vector3()).length() || 1) * 0.0001;
    // Stack labels on the same face instead of covering each other.
    const faceOffsets = new Map();
    for (const entry of entries) {
      // On curved faces the first glyph may be behind the solid. Anchor the
      // label to a visible glyph, retaining occlusion when the entire face is hidden.
      let projected;
      for (const point of entry.points) {
        const candidate = point.clone().project(this.camera);
        if (Math.abs(candidate.x) > 1 || Math.abs(candidate.y) > 1 || Math.abs(candidate.z) > 1) continue;
        const direction = point.clone().sub(this.camera.position);
        const distance = direction.length();
        this.boundaryRaycaster.set(this.camera.position, direction.normalize());
        const first = this.boundaryRaycaster.intersectObjects(this.meshes, false)[0];
        if (!entry.alwaysVisible && first && first.distance < distance - tolerance) continue;
        projected = candidate;
        break;
      }
      entry.element.hidden = !projected;
      if (!projected) continue;
      const offset = faceOffsets.get(entry.faceKey) || 0;
      faceOffsets.set(entry.faceKey, offset + 1);
      entry.element.style.left = `${(projected.x + 1) * width / 2}px`;
      entry.element.style.top = `${(1 - projected.y) * height / 2 + offset * 24}px`;
    }
  }

  pick(event) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hit = this.raycaster.intersectObjects(this.meshes, false)[0];
    return hit ? { key: hit.object.userData.triangleToFaceKey[hit.faceIndex], point: hit.point } : null;
  }

  frame(box, reset = false) {
    this.cancelFocus();
    if (!box || box.isEmpty()) return;
    const center = box.getCenter(new THREE.Vector3());
    const modelSize = this.bounds.getSize(new THREE.Vector3()).length() || 1;
    const size = Math.max(box.getSize(new THREE.Vector3()).length(), modelSize * 0.03);
    const distance = size / (2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2))) * 1.25 / Math.min(this.camera.aspect, 1);
    const direction = reset ? new THREE.Vector3(1, -1.4, 0.9).normalize() : this.camera.position.clone().sub(this.controls.target).normalize();
    this.camera.position.copy(center).addScaledVector(direction, distance);
    this.controls.target.copy(center);
    this.camera.near = Math.max(modelSize / 100000, 0.000001);
    this.camera.far = Math.max(modelSize * 1000, distance * 10);
    this.controls.minDistance = modelSize * 0.0001;
    this.controls.maxDistance = modelSize * 100;
    this.camera.updateProjectionMatrix();
    this.controls.update();
  }

  fit(reset = false) { this.frame(this.bounds, reset); }
  focus(key) {
    this.cancelFocus();
    this.scene.updateMatrixWorld(true);
    const pose = faceFocusPose(this.faces.get(key), this.bounds, this.camera, this.controls.target, this.meshes);
    if (!pose) return;
    const damping = this.controls.enableDamping;
    this.controls.enableDamping = false;
    this.controls.update();
    const direction = this.camera.position.clone().sub(this.controls.target);
    const distance = direction.length();
    direction.normalize();
    const endDirection = pose.position.clone().sub(pose.target).normalize();
    const rotation = new THREE.Quaternion().setFromUnitVectors(direction, endDirection);
    if (direction.dot(endDirection) < -0.9999) {
      const axis = this.camera.up.clone().addScaledVector(direction, -this.camera.up.dot(direction));
      if (axis.lengthSq() > 1e-8) rotation.setFromAxisAngle(axis.normalize(), Math.PI);
    }
    this.focusAnimation = { pose, damping, started: performance.now(), direction, distance,
      target: this.controls.target.clone(), up: this.camera.up.clone(),
      rotation,
      endDistance: pose.position.distanceTo(pose.target) };
    if (globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches) this.updateFocus(true);
  }

  cancelFocus() {
    if (!this.focusAnimation) return;
    this.controls.enableDamping = this.focusAnimation.damping;
    this.focusAnimation = null;
  }

  updateFocus(finish = false) {
    const animation = this.focusAnimation;
    if (!animation) return;
    const t = finish ? 1 : Math.min((performance.now() - animation.started) / 450, 1);
    const eased = t * t * (3 - 2 * t);
    const rotation = new THREE.Quaternion().slerp(animation.rotation, eased);
    const direction = animation.direction.clone().applyQuaternion(rotation);
    this.controls.target.lerpVectors(animation.target, animation.pose.target, eased);
    this.camera.position.copy(this.controls.target).addScaledVector(direction,
      THREE.MathUtils.lerp(animation.distance, animation.endDistance, eased));
    this.camera.up.lerpVectors(animation.up, animation.pose.up, eased).normalize();
    this.camera.lookAt(this.controls.target);
    if (t === 1) this.cancelFocus();
    this.labelsDirty = true;
  }

  updateClipping() {
    if (!this.boundingSphere) return;
    const { center, radius } = this.boundingSphere;
    const distance = this.camera.position.distanceTo(center);
    // Keep the complete model in view while using a tight depth range. The
    // old 100,000,000:1 range made thin/curved faces visibly fight for depth.
    const near = Math.max(distance - radius * 1.2, radius * 0.0001, 0.000001);
    const far = Math.max(distance + radius * 2, near * 2);
    if (this.camera.near !== near || this.camera.far !== far) {
      this.camera.near = near;
      this.camera.far = far;
      this.camera.updateProjectionMatrix();
    }
  }

  dispose() {
    this.cancelFocus();
    this.renderer.setAnimationLoop(null);
    this.resize.disconnect();
    this.controls.dispose();
    this.orientationAxes.dispose();
    this.disposeGroup(this.scene);
    this.renderer.dispose();
    this.renderer.domElement.remove();
    this.boundaryLabels.remove();
    this.gravityLabels.remove();
  }
}
