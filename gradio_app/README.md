# Gradio + Python CAD workspace

This implementation combines native Gradio controls and a Python backend with
the original Three.js viewer. Only rendering, picking, and annotation graphics
are reused, not the old UI, importer, or IndexedDB workflows. Python supplies
the geometry and authoritative face IDs. The standalone Vite app still works.

## Run (Python 3.11 or 3.12 recommended)

From the repository root in PowerShell:

```powershell
python -m venv .venv-gradio
.\.venv-gradio\Scripts\python.exe -m pip install -r requirements-gradio.txt
npm.cmd install
.\.venv-gradio\Scripts\python.exe -m gradio_app.app
```

Open http://127.0.0.1:7860. Node.js is needed to build the reused viewer. Startup
automatically runs `npm.cmd run build:gradio` when its bundle is missing or stale.
The bundle is served by Gradio; no separate Vite server or CDN is needed.
Review/annotation needs no Ansys installation or license; simulation requires
Mechanical 261 and a usable license. On macOS/Linux use
`.venv-gradio/bin/python` and `npm` instead. Options:
`--port 7861 --data-dir path/to/data`. `STEP_GRADIO_DATA` also sets the data directory.

## Workflow

1. Upload a STEP file. Python OpenCascade imports the original B-rep, converts
   lengths to mm, and tessellates each original face separately.
2. Hover over geometry to preview a whole face in teal; click to select it in
   amber. **Select whole CAD face** remains available for keyboard navigation.
   Drag to orbit, right-drag to pan, and scroll to zoom. **Fit model** and
   **Reset view** reframe the model. Empty clicks, **Clear face**, or Escape
   with the canvas focused clear selection. Orbit drags do not select faces.
3. Save comments or apply fixed support, prescribed displacement (mm), total
   face force (N), or signed pressure (MPa). Multiple records may share a face.
4. Choose an existing annotation to navigate to its face and edit it. Choose
   **New comment/condition** to stop editing. Changing faces clears all drafts.
5. To delete, select the record, check its confirmation box, and delete.
6. Refreshing the page clears session selection, not saved projects. Refresh
   the saved-project list and reopen, or upload the same STEP bytes again.
7. Export JSON for annotation backups. Import merges by record ID after validating
   the whole file, model hash, values, and timestamps. Unmapped records remain
   visible and deletable, but cannot silently attach to another face.

## Differences from the browser iteration

- The Gradio HTML bridge loads `src/gradio/bridge.js`, which imports the same
  `src/viewer/scene.js` as the standalone app. Picks flow through Gradio events,
  not DOM scraping or a separate API client. Python validates picked face keys
  and ignores clicks queued before another model replaced the current one.
- Python's geometry cache produces an indexed mesh with explicit inclusive
  triangle ranges and face identities. JavaScript does not re-import STEP or
  invent its own IDs. The original viewer accepts these external identities.
- Hover, click picking, camera controls, condition tints, directional arrows,
  support glyphs, and camera-tracked labels are available. Selection and annotation
  updates preserve the camera and canvas; dropdown/annotation navigation frames
  the destination face.
- Processing and persistence are **server-side**, not IndexedDB. The default
  server is loopback-only, with no public sharing. Do not expose it as a multiuser
  service without authentication and per-user project isolation. All local users
  of this server share saved projects.
- SQLite stores documents; original STEP bytes, mesh caches, viewer geometry, and
  JSON downloads live in `gradio-data/`. Back up this directory and retain the
  original STEP. Previews/exports accumulate; stop the app before clearing only
  those two derived directories if needed. Original models and the DB are private;
  only static viewer assets, previews, and exports are explicitly allowed for
  Gradio downloads.
- Python face keys use `python-ocp-v1:face:N`, bound to the exact SHA-256 and
  OpenCascade traversal. They are **not compatible** with the browser importer's
  occurrence keys. Browser version-1/2 JSON imports as unmapped; no invented
  cross-importer mapping is attempted. Do not upgrade the CAD importer and assume
  cached face indices still match newly imported geometry.
- No full assembly tree/name UI or comment pins are included. STEP
  placements are applied when tessellating each face. Native imports are queued;
  there is no worker cancellation for a running OpenCascade import.

## Ansys Mechanical simulation

The **Ansys Mechanical** accordion runs a deterministic single-solid linear
static structural analysis using saved face annotations. It uses a separate
PyMechanical interpreter, explicit Structural Steel material, mesh size, one
solver core, and no weak springs. It displays deformation and von Mises stress
contours and exports the complete run. See [`mechanical/README.md`](../mechanical/README.md)
for the analysis contract, fail-closed face mapping, CLI commands, limitations,
and actual Mechanical regression tests.

**The PyMechanical environment is an input.** Enter its Python executable in
**Mechanical Python executable**, or set `MECHANICAL_PYTHON` before app startup.
The field is empty when that variable is unset; the app does not search personal
directories or assume Gradio's environment includes PyMechanical. Install
`requirements-mechanical.txt` in the supplied environment and ensure it can
access Mechanical 261 and its license. See the [root setup example](../README.md#required-simulation-input-pymechanical-environment).

`backend.Workspace` is independent of Gradio. `project_snapshot(model_id)` exposes
the exact model hash, comments, typed boundary conditions, explicit mm/N/MPa units,
and each face's index, area, and centroid. The original STEP is at
`workspace.root / "models" / f"{model_id}.step"`.

The adapter imports that STEP in a fresh Mechanical process and resolves each
face using area, centroid, exact interior surface samples, and outward normals.
**OpenCascade keys are not Mechanical geometry IDs.** Ambiguous mappings stop
the run; no arbitrary nearest-face fallback is used.

## Tests

```powershell
.\.venv-gradio\Scripts\python.exe -m unittest discover -s tests/python -v
npm.cmd test
npx.cmd playwright install chromium
npm.cmd run test:gradio
```

Tests generate real STEP boxes/cylinders with OpenCascade, verify whole curved
faces and units/placements, round-trip native previews and annotations, reject
invalid imports atomically, restore persisted projects, and construct the Gradio UI.
Playwright starts an isolated Gradio server on port 7862 and verifies actual canvas
picking, Gradio synchronization, boundary graphics, stable canvas mounting,
dropdown navigation, and orbit-drag suppression.
