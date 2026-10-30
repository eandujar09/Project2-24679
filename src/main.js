import './styles.css';
import { Viewer } from './viewer/scene.js';
import { importStep, modelHash } from './cad/stepImporter.js';
import { store } from './comments/commentStore.js';
import { exportAnnotations, validateProjectAnnotations } from './comments/exportImport.js';
import { BoundaryPanel } from './boundaries/panel.js';
import { validateConditions } from './boundaries/conditions.js';

document.querySelector('#app').innerHTML = `
  <header class="toolbar">
    <div class="brand"><span class="brand-icon" aria-hidden="true">◈</span><div><h1>STEP Face Comments</h1><span class="eyebrow">LOCAL CAD REVIEW</span></div></div>
    <nav aria-label="Model tools">
      <button id="upload" class="primary">Open STEP</button>
      <button id="fit" disabled>Fit model</button><button id="reset" disabled>Reset view</button>
      <span class="divider"></span><button id="export" disabled>Export JSON</button><button id="import" disabled>Import JSON</button>
    </nav>
  </header>
  <input id="step-file" type="file" accept=".step,.stp" hidden />
  <input id="json-file" type="file" accept=".json,application/json" hidden />
  <div id="error" class="notice error" role="alert" hidden><span></span><button aria-label="Dismiss error">×</button></div>
  <div id="message" class="notice" role="status" hidden></div>
  <div id="restore" class="notice" hidden><span></span><button id="reopen">Reopen project</button><button id="dismiss-restore">Dismiss</button></div>
  <main>
    <section id="viewport" aria-label="Model viewer">
      <div class="viewport-label"><span class="live-dot"></span> MODEL SPACE <span id="view-label">No model loaded</span></div>
      <div id="welcome" class="empty-view"><div class="model-icon" aria-hidden="true">⬡</div><h2>A place for precise feedback.</h2><p>Open a STEP model. Select a whole CAD face.<br>Keep every comment right where it belongs.</p><button id="empty-upload" class="primary">Choose a STEP file</button><small>or drop a .step / .stp file here · stays on this device</small></div>
      <div id="loading" class="loading" role="status" hidden><span class="spinner"></span><strong>Preparing your model</strong><span id="loading-text">Reading STEP geometry…</span><button id="cancel-load">Cancel</button></div>
      <div id="drop-overlay" hidden>Drop STEP file to open</div>
      <div class="viewport-help">DRAG <span>Orbit</span> <b>·</b> RIGHT DRAG <span>Pan</span> <b>·</b> SCROLL <span>Zoom</span></div>
      <div class="legend"><span class="hover-dot"></span> Hover <span class="selected-dot"></span> Selected<br><span class="fixed-dot"></span> Fixed <span class="force-dot"></span> Force <span class="pressure-dot"></span> Pressure <span class="displacement-dot"></span> Displacement</div>
    </section>
    <aside aria-label="Face comments">
      <section class="selection-panel"><div class="section-heading"><h2>Selected face</h2><button id="clear" class="subtle" disabled>Clear</button></div><p id="selected-name">Select a face on the model</p><code id="face-key">No face selected</code>
        <label for="face-picker">Browse CAD faces</label><select id="face-picker" disabled><option value="">Open a model first</option></select>
      </section>
      <section id="boundary-panel" aria-label="Boundary conditions"></section>
      <section class="composer-panel"><h2 id="composer-title">New comment</h2><form id="comment-form"><label class="sr-only" for="comment-text">Comment text</label><textarea id="comment-text" rows="4" placeholder="Select a face, then leave a note…" disabled required maxlength="20000"></textarea><div class="composer-actions"><span id="composer-hint">Attached to the selected CAD face</span><button id="cancel-edit" type="button" hidden>Cancel edit</button><button id="save-comment" class="primary" disabled>Add comment</button></div></form></section>
      <section class="comments-panel"><div class="section-heading"><h2>Comments <span id="comment-count" class="badge">0</span></h2><label class="filter"><input id="filter" type="checkbox" /> Selected face</label></div><div id="comments"></div></section>
      <div class="privacy-note">◈ Local-first workspace<br><span>Your model and notes stay in this browser.</span></div>
    </aside>
  </main>
  <footer><span id="model-status">Ready to open a STEP model</span><span id="save-status">Local storage · IndexedDB</span></footer>
`;

const $ = id => document.getElementById(id);
let model = null;
let comments = [];
let boundaryConditions = [];
let selected = null;
let anchor;
let editing = null;
let loading = false;
let writing = false;
let importController;
let generation = 0;
let viewer;

function error(message) {
  $('error').firstElementChild.textContent = message;
  $('error').hidden = false;
}
function notify(message) {
  $('message').textContent = message;
  $('message').hidden = false;
}
$('error').querySelector('button').onclick = () => { $('error').hidden = true; };

try { viewer = new Viewer($('viewport'), (key, point) => { if (!loading && !writing) selectFace(key, point); }); }
catch { error('WebGL could not start. Enable hardware acceleration and reload in a WebGL-capable browser.'); }
$('viewport').addEventListener('viewer-error', e => error(e.detail));

const boundaryPanel = new BoundaryPanel($('boundary-panel'), {
  onSelect: key => selectFace(key, undefined, true),
  onSave: draft => {
    if (!model || !selected || writing || loading) return;
    const existing = boundaryConditions.find(condition => condition.id === draft.id);
    const now = new Date().toISOString();
    let condition;
    try {
      [condition] = validateConditions([{ ...draft, id: existing?.id || crypto.randomUUID(), modelId: model.id,
        createdAt: existing?.createdAt || now, updatedAt: now }], model.id);
    } catch (e) { error(e.message); return; }
    mutate(async () => {
      await store.putBoundary(condition);
      boundaryConditions = [...boundaryConditions.filter(item => item.id !== condition.id), condition];
      viewer.setBoundaryConditions(boundaryConditions);
      boundaryPanel.reset();
    });
  },
  onDelete: condition => mutate(async () => {
    await store.deleteBoundary(condition.id);
    boundaryConditions = boundaryConditions.filter(item => item.id !== condition.id);
    viewer.setBoundaryConditions(boundaryConditions);
    if (boundaryPanel.editing === condition.id) boundaryPanel.reset();
  }),
});

function resetEditor() {
  editing = null;
  $('comment-text').value = '';
  $('composer-title').textContent = 'New comment';
  $('save-comment').textContent = 'Add comment';
  $('cancel-edit').hidden = true;
}

function selectFace(key, point, focus = false) {
  if (key && !viewer.faces.has(key)) { error(`This annotation refers to a missing CAD face: ${key}`); return; }
  if (key !== selected) resetEditor();
  selected = key;
  anchor = point;
  viewer?.select(key);
  if (focus && key) viewer.focus(key);
  render();
}

function render() {
  const available = !!model && !loading && !writing;
  for (const id of ['fit', 'reset', 'export', 'import']) $(id).disabled = !available;
  $('upload').disabled = writing;
  $('empty-upload').disabled = writing;
  $('face-picker').disabled = !available;
  $('clear').disabled = !selected || !available;
  $('comment-text').disabled = !selected || !available;
  $('save-comment').disabled = !selected || !available;
  $('cancel-edit').disabled = !available;
  $('selected-name').textContent = selected ? `${viewer.faces.get(selected).name} · Face ${viewer.faces.get(selected).faceIndex}` : 'Select a face on the model';
  $('face-key').textContent = selected || 'No face selected';
  $('face-picker').value = selected || '';
  $('comment-count').textContent = comments.length;
  $('model-status').textContent = model ? `${model.filename}  ·  ${viewer.faces.size} faces  ·  ${comments.length} comments  ·  ${boundaryConditions.length} conditions` : 'Ready to open a STEP model';
  boundaryPanel.render({ selected, conditions: boundaryConditions, faces: viewer?.faces || new Map(), available });
  $('view-label').textContent = model?.filename || 'No model loaded';
  $('comments').replaceChildren();
  const visible = comments.filter(c => !$('filter').checked || c.faceKey === selected).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  if (!visible.length) {
    const empty = document.createElement('p');
    empty.className = 'empty-comments';
    empty.textContent = comments.length ? 'No comments on this face.' : 'No comments yet. Select a face and start the conversation.';
    $('comments').append(empty);
  }
  for (const comment of visible) {
    const card = document.createElement('article');
    card.className = `comment-card${comment.faceKey === selected ? ' active' : ''}`;
    const face = viewer.faces.get(comment.faceKey);
    const jump = document.createElement('button');
    jump.className = 'comment-jump';
    jump.textContent = face ? `Face ${face.faceIndex} · ${face.name}` : 'Unmapped face';
    jump.title = comment.faceKey;
    jump.disabled = !available;
    jump.onclick = () => selectFace(comment.faceKey, comment.anchor, true);
    const text = document.createElement('p');
    text.textContent = comment.text;
    const date = document.createElement('time');
    date.dateTime = comment.updatedAt;
    date.textContent = `${comment.updatedAt !== comment.createdAt ? 'Edited ' : ''}${new Date(comment.updatedAt).toLocaleString()}`;
    date.title = `Created: ${comment.createdAt}\nUpdated: ${comment.updatedAt}`;
    const actions = document.createElement('div');
    actions.className = 'comment-actions';
    const edit = document.createElement('button');
    edit.textContent = 'Edit'; edit.disabled = !available || !face;
    edit.onclick = () => {
      selectFace(comment.faceKey, comment.anchor, true);
      editing = comment.id;
      $('comment-text').value = comment.text;
      $('composer-title').textContent = 'Edit comment';
      $('save-comment').textContent = 'Save changes';
      $('cancel-edit').hidden = false;
      $('comment-text').focus();
    };
    const remove = document.createElement('button');
    remove.textContent = 'Delete'; remove.disabled = !available;
    remove.onclick = () => {
      if (confirm('Delete this comment? This cannot be undone.')) mutate(async () => {
        await store.delete(comment.id);
        comments = comments.filter(c => c.id !== comment.id);
        if (editing === comment.id) resetEditor();
      });
    };
    actions.append(date, edit, remove);
    card.append(jump, text, actions);
    $('comments').append(card);
  }
}

async function mutate(action) {
  if (writing || loading) return;
  writing = true; render();
  $('save-status').textContent = 'Saving…';
  try { await action(); $('save-status').textContent = 'Saved locally'; }
  catch (e) { error(`Could not save: ${e.message}`); $('save-status').textContent = 'Save failed'; }
  finally { writing = false; render(); }
}

async function loadFile(file) {
  if (!file || writing) return;
  if (!viewer) { error('The 3D viewer is unavailable. Reload with WebGL enabled.'); return; }
  if (!/\.(step|stp)$/i.test(file.name)) { error('Choose a STEP file with a .step or .stp extension.'); return; }
  importController?.abort();
  const controller = new AbortController();
  importController = controller;
  const token = ++generation;
  loading = true;
  $('loading').hidden = false;
  $('loading-text').textContent = 'Reading STEP geometry in a background worker…';
  $('error').hidden = true; $('message').hidden = true; $('restore').hidden = true;
  render();
  try {
    const buffer = await file.arrayBuffer();
    const id = await modelHash(buffer);
    if (token !== generation || controller.signal.aborted) return;
    const result = await importStep(buffer, controller.signal);
    let restored = [];
    let restoredBoundaries = [];
    let storageError;
    try { [restored, restoredBoundaries] = await Promise.all([store.comments(id), store.boundaries(id)]); } catch (e) { storageError = e; }
    if (token !== generation || controller.signal.aborted) return;
    viewer.load(result);
    model = { id, filename: file.name, importedAt: new Date().toISOString(), fileBlob: file };
    comments = restored;
    boundaryConditions = restoredBoundaries;
    viewer.setBoundaryConditions(boundaryConditions);
    boundaryPanel.reset();
    selected = null; anchor = undefined; resetEditor();
    const options = [new Option('Choose a face…', '')];
    for (const [key, face] of viewer.faces) options.push(new Option(`${face.name} · Face ${face.faceIndex}`, key));
    $('face-picker').replaceChildren(...options);
    $('welcome').hidden = true;
    $('save-status').textContent = 'Saving model…';
    try { await store.saveModel(model); $('save-status').textContent = 'Saved locally'; }
    catch (e) { storageError = e; $('save-status').textContent = 'Model not saved'; }
    if (token !== generation) return;
    if (storageError) error(`Local storage is unavailable or full: ${storageError.message}. Model is open; check browser storage settings.`);
    const unmapped = [...comments, ...boundaryConditions].filter(c => !viewer.faces.has(c.faceKey)).length;
    if (unmapped) notify(`${unmapped} annotations refer to missing faces and are shown as unmapped.`);
  } catch (e) {
    if (e.name !== 'AbortError' && token === generation) error(`Could not open STEP: ${e.message}`);
  } finally {
    if (token === generation) { loading = false; $('loading').hidden = true; render(); }
  }
}

$('upload').onclick = $('empty-upload').onclick = () => $('step-file').click();
$('step-file').onchange = e => { loadFile(e.target.files[0]); e.target.value = ''; };
$('cancel-load').onclick = () => importController?.abort();
$('fit').onclick = () => viewer.fit();
$('reset').onclick = () => viewer.fit(true);
$('clear').onclick = () => selectFace(null);
$('face-picker').onchange = e => selectFace(e.target.value || null, undefined, true);
$('filter').onchange = render;
$('cancel-edit').onclick = resetEditor;
$('comment-form').onsubmit = e => {
  e.preventDefault();
  const text = $('comment-text').value.trim();
  if (!selected || !text || loading || writing) return;
  const existing = editing ? comments.find(c => c.id === editing) : null;
  const now = new Date().toISOString();
  const comment = existing ? { ...existing, text, updatedAt: now } : {
    id: crypto.randomUUID(), modelId: model.id, faceKey: selected, text, createdAt: now, updatedAt: now,
    ...(anchor ? { anchor } : {}),
  };
  mutate(async () => {
    await store.put(comment);
    comments = [...comments.filter(c => c.id !== comment.id), comment];
    resetEditor();
  });
};
$('export').onclick = () => exportAnnotations(model, comments, boundaryConditions);
$('import').onclick = () => $('json-file').click();
$('json-file').onchange = async e => {
  const file = e.target.files[0]; e.target.value = '';
  if (!file || !model || loading || writing) return;
  // Lock the project during JSON parsing as well as its database transaction.
  mutate(async () => {
    const incoming = validateProjectAnnotations(JSON.parse(await file.text()), model.id);
    await store.merge(incoming.comments, model.id, incoming.boundaryConditions);
    [comments, boundaryConditions] = await Promise.all([store.comments(model.id), store.boundaries(model.id)]);
    viewer.setBoundaryConditions(boundaryConditions);
    boundaryPanel.reset();
    const unmapped = [...incoming.comments, ...incoming.boundaryConditions].filter(c => !viewer.faces.has(c.faceKey)).length;
    notify(`Imported ${incoming.comments.length} comments and ${incoming.boundaryConditions.length} boundary conditions.${unmapped ? ` ${unmapped} have missing face mappings and remain unmapped.` : ''}`);
  });
};

window.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !loading && !writing) { selectFace(null); viewer?.hover(null); }
});
let dragDepth = 0;
window.addEventListener('dragenter', e => {
  if (Array.from(e.dataTransfer.types).includes('Files')) { e.preventDefault(); dragDepth++; $('drop-overlay').hidden = false; }
});
window.addEventListener('dragover', e => { e.preventDefault(); });
window.addEventListener('dragleave', () => { if (--dragDepth <= 0) { dragDepth = 0; $('drop-overlay').hidden = true; } });
window.addEventListener('drop', e => {
  e.preventDefault(); dragDepth = 0; $('drop-overlay').hidden = true;
  loadFile(e.dataTransfer.files[0]);
});

render();
const initialGeneration = generation;
store.lastModel().then(last => {
  if (!last || generation !== initialGeneration || model || loading) return;
  $('restore').firstElementChild.textContent = `Previous project: ${last.filename}`;
  $('restore').hidden = false;
  $('reopen').onclick = () => loadFile(new File([last.fileBlob], last.filename));
}).catch(e => error(`Cannot access local storage: ${e.message}`));
$('dismiss-restore').onclick = () => { $('restore').hidden = true; };
