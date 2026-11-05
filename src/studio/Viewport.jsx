import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { Viewer } from '../viewer/scene.js';
import { CustomIcon as Icon } from './vendor/zoo/CustomIcon';
import { captureFrame, pickFrame, setCameraView } from './visual';
import { gravitySummary } from '../viewer/gravityVisuals.js';

export const Viewport = forwardRef(function Viewport({ state, onSelect, onUpload, disabled, theme, children }, ref) {
  const host = useRef(null), viewer = useRef(null), latest = useRef(state), select = useRef(onSelect);
  const visualFrames = useRef(new Map()), ready = useRef(null);
  const [loaded, setLoaded] = useState(null), [error, setError] = useState(''), [drag, setDrag] = useState(false);
  latest.current = state;
  select.current = onSelect;
  useEffect(() => {
    try {
      const scene = new Viewer(host.current, key => { if (latest.current?.modelId) select.current(key); });
      viewer.current = scene;
      scene.scene.background.set(theme === 'dark' ? '#1d1d1d' : '#f7f7f7');
      const hostElement = host.current;
      const reportError = e => setError(e.detail);
      hostElement.addEventListener('viewer-error', reportError);
      return () => { hostElement.removeEventListener('viewer-error', reportError); scene.dispose(); };
    } catch (e) { setError('The 3D view could not start. Enable hardware acceleration and reload.'); }
  }, []);
  useEffect(() => { viewer.current?.scene.background.set(theme === 'dark' ? '#1d1d1d' : '#f7f7f7'); }, [theme]);
  useEffect(() => {
    if (!state?.modelId || !viewer.current) return;
    const controller = new AbortController();
    setLoaded(null); setError('');
    ready.current = null; visualFrames.current.clear();
    (async () => {
      const response = await fetch(state.geometryUrl, { signal: controller.signal });
      if (!response.ok) throw new Error('The CAD preview could not be loaded. Try opening the model again.');
      const geometry = await response.json();
      if (controller.signal.aborted) return;
      viewer.current.load(geometry.result, { faceIdentities: geometry.faceIdentities });
      viewer.current.meshes.forEach(mesh => { mesh.material.color.set('#aab4bd'); mesh.material.metalness = 0.15; mesh.material.roughness = 0.65; });
      setLoaded(state.modelId);
      ready.current = state.modelId;
    })().catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    return () => controller.abort();
  }, [state?.modelId, state?.geometryUrl]);
  const conditionKey = useRef(''), gravityKey = useRef(''), focusToken = useRef(null);
  useEffect(() => {
    const scene = viewer.current;
    if (!scene || loaded !== state?.modelId || !loaded) return;
    const key = JSON.stringify([loaded, state.boundaryConditions, state.proposedBoundaryConditions]);
    if (conditionKey.current !== key) {
      scene.setBoundaryConditions(state.boundaryConditions || [], state.proposedBoundaryConditions || []);
      conditionKey.current = key;
    }
    const nextGravity = JSON.stringify([loaded, state.gravityLoads]);
    if (gravityKey.current !== nextGravity) {
      scene.setGravity(state.gravityLoads || []);
      gravityKey.current = nextGravity;
    }
    scene.select(state.selected || null);
    scene.highlight(state.highlighted || []);
    const token = `${loaded}:${state.focusToken}`;
    if (state.focusFace && focusToken.current !== token) scene.focus(state.focusFace);
    focusToken.current = token;
  }, [state, loaded]);
  useImperativeHandle(ref, () => ({
    fit() { viewer.current?.fit(); },
    view(name) {
      setCameraView(viewer.current, name);
    },
    visual(request) {
      const scene = viewer.current;
      if (!scene || ready.current !== request.modelId || latest.current?.modelId !== request.modelId) throw new Error('The CAD view is still loading. Try capturing it again.');
      if (request.tool === 'capture_viewport') {
        setCameraView(scene, request.view);
        const frame = captureFrame(scene, request.modelId);
        visualFrames.current.set(request.id, frame);
        if (visualFrames.current.size > 4) visualFrames.current.delete(visualFrames.current.keys().next().value);
        return { image: frame.image };
      }
      if (request.tool !== 'pick_viewport_face') throw new Error('Unknown viewport action.');
      return { face_key: pickFrame(scene, visualFrames.current.get(request.frame_id), request.modelId, request.x, request.y) };
    },
    image() {
      const scene = viewer.current;
      if (!scene) return;
      scene.render();
      const link = document.createElement('a'); link.download = 'cad-view.png'; link.href = scene.renderer.domElement.toDataURL('image/png'); link.click();
    },
  }), []);
  return <div className={`viewport-wrap ${drag ? 'drag-over' : ''}`} onDragOver={e => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); if (!disabled) setDrag(true); } }}
    onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget)) setDrag(false); }}
    onDrop={e => { e.preventDefault(); setDrag(false); if (!disabled && e.dataTransfer.files[0]) onUpload(e.dataTransfer.files[0]); }}>
    <div ref={host} className="studio-canvas" data-testid="cad-viewport" data-model-id={loaded || ''} data-selected-face={state?.selected || ''} data-highlighted-faces={JSON.stringify(state?.highlighted || [])}/>
    {!!state?.gravityLoads?.length && loaded === state.modelId && <div className="gravity-status" role="status">
      {state.gravityLoads.map(load => <div key={load.id} data-gravity-state={load.state} className={load.state === 'proposed' ? 'proposed' : ''} title="Physical gravity in the design coordinate system. Applies to all bodies.">{gravitySummary(load)}</div>)}
    </div>}
    {error ? <div className="viewport-message error"><Icon name="triangleExclamation" width={28}/><p>{error}</p></div>
      : !state?.modelId ? <div className="viewport-message empty-model">
        <div className="model-outline"><Icon name="model" width={60} height={60}/></div>
        <h1>Your model. Ready for analysis.</h1><p>Drop a STEP file into the workspace<br/>or choose a model to get started.</p>
        <label className={`import-main ${disabled ? 'disabled' : ''}`}><Icon name="importFile" width={18}/>Import CAD<input type="file" accept=".step,.stp" aria-label="Import CAD model" disabled={disabled} onChange={e => { if (e.target.files[0]) onUpload(e.target.files[0]); e.target.value = ''; }}/></label>
        <span className="file-formats">STEP / STP</span>
      </div> : loaded !== state.modelId ? <div className="viewport-message loading"><span className="spinner"/>Preparing CAD geometry…</div> : null}
    {drag && <div className="drop-overlay">Drop your STEP model here</div>}
    {children}
  </div>;
});
