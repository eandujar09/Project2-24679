import { Viewer } from '../viewer/scene.js';
import './viewer.css';

// Only presentation lives here. Geometry, identity and annotations are Python-owned.
export function mount(element, props, trigger, watch) {
  const container = element.querySelector('.python-cad-viewer');
  const toolbar = document.createElement('div');
  toolbar.className = 'cad-toolbar';
  container.append(toolbar);
  const viewport = document.createElement('div');
  viewport.className = 'cad-viewport';
  container.append(viewport);
  const status = document.createElement('div');
  status.className = 'cad-status';
  status.setAttribute('role', 'status');
  container.append(status);
  let currentModel = null;
  let loadedUrl = null;
  let loading = false;
  let version = 0;
  let controller;
  let disposed = false;
  let conditionsJSON;
  let state = {};
  let viewer;
  const report = message => { status.textContent = message; };
  const emit = key => {
    if (loading || !currentModel || disposed) return;
    viewer.select(key);
    trigger('select', { modelId: currentModel, faceKey: key });
  };
  try { viewer = new Viewer(viewport, emit); }
  catch { report('WebGL could not start. Enable hardware acceleration and reload.'); return; }
  viewport.addEventListener('viewer-error', event => report(event.detail));
  for (const [label, action] of [
    ['Fit model', () => viewer.fit()], ['Reset view', () => viewer.fit(true)],
    ['Clear face', () => emit(null)],
  ]) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.addEventListener('click', action);
    toolbar.append(button);
  }
  const keydown = event => { if (event.key === 'Escape') { emit(null); viewer.hover(null); } };
  viewport.addEventListener('keydown', keydown);

  async function update() {
    const token = ++version;
    try {
      state = props.value ? JSON.parse(props.value) : {};
      if (!state.modelId) { report('Open a STEP model to begin.'); return; }
      if (currentModel !== state.modelId || loadedUrl !== state.geometryUrl) {
        controller?.abort();
        controller = new AbortController();
        loading = true;
        report('Loading Python CAD geometry…');
        const response = await fetch(state.geometryUrl, { signal: controller.signal });
        if (!response.ok) throw new Error(`Geometry request failed (${response.status}).`);
        const geometry = await response.json();
        if (token !== version || disposed) return;
        viewer.load(geometry.result, { faceIdentities: geometry.faceIdentities });
        currentModel = state.modelId;
        loadedUrl = state.geometryUrl;
        conditionsJSON = undefined;
      }
      if (token !== version || disposed) return;
      const nextConditions = JSON.stringify(state.boundaryConditions || []);
      if (nextConditions !== conditionsJSON) {
        viewer.setBoundaryConditions(state.boundaryConditions || []);
        conditionsJSON = nextConditions;
      }
      viewer.select(state.selected || null);
      if (state.focus && state.selected) viewer.focus(state.selected);
      report(`${viewer.faces.size} CAD faces · click a face to select · drag to orbit · right-drag to pan · scroll to zoom`);
    } catch (error) {
      if (error.name !== 'AbortError' && token === version) report(`CAD preview: ${error.message}`);
    } finally {
      if (token === version) loading = false;
    }
  }
  watch('value', update);
  update();
  // HTML components may be unmounted by Gradio navigation; free GPU resources.
  const observer = new MutationObserver(() => {
    if (!element.isConnected) {
      disposed = true;
      controller?.abort();
      viewer.dispose();
      observer.disconnect();
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
}
