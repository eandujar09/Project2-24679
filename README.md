# STEP Face Comments

A local-first browser workspace for reviewing STEP CAD models and attaching comments and boundary conditions to **whole original B-rep faces**. Implemented from [`STEP_FACE_COMMENTS.md`](./STEP_FACE_COMMENTS.md).

## Python / native Gradio iteration

A Gradio app with Python OpenCascade processing and server-side persistence is
available in [`gradio_app/`](./gradio_app/README.md). It reuses the interactive
viewer for whole-face click picking and boundary-condition graphics, while Python
owns geometry, face IDs, and storage. A [deterministic Mechanical runner](./mechanical/README.md)
can apply saved conditions, solve a single-solid static structural analysis, and
display deformation/stress results in Gradio.
See its README for setup, differences, and tests.

### Required simulation input: PyMechanical environment

The **PyMechanical Python environment is a user-provided input**, not bundled
with this repository. Annotation alone does not require it. To run simulations,
install Ansys Mechanical **2026 R1 (261)** with a usable license and create or
reuse a compatible Python environment containing `requirements-mechanical.txt`:

```powershell
python -m venv .venv-mechanical
.\.venv-mechanical\Scripts\python.exe -m pip install -r requirements-mechanical.txt
$env:MECHANICAL_PYTHON = (Resolve-Path .\.venv-mechanical\Scripts\python.exe).Path
.\.venv-gradio\Scripts\python.exe -m gradio_app.app
```

Set up `.venv-gradio` first using the [Gradio instructions](./gradio_app/README.md).
Alternatively, enter the interpreter path directly in **Mechanical Python
executable** in the app. Without `MECHANICAL_PYTHON`, this field starts empty;
there is no automatic search of personal directories. The interpreter must have
PyMechanical installed and access to Mechanical and its license. On macOS/Linux,
virtual environments use `bin/python`; Mechanical execution still requires a
supported Ansys host. See the [Mechanical guide](./mechanical/README.md).

### Publishing this repository

Virtual environments, dependencies, build outputs, test artifacts, and local
CAD/annotation/simulation data are excluded by `.gitignore`. Keep local interpreter
paths in your shell environment or the app input, not in committed source files.
Before pushing, review `git status --short` and the staged files. Do not force-add
`gradio-data/` or `test-results/`: their models, databases, reports, and archives
can contain private CAD data and absolute local paths. Custom `--data-dir` or CLI
output directories should be outside the repository or added to `.gitignore`.

## Run locally

Requires Node.js 20.19+ or 22.12+ (Node 24 is supported).

```powershell
npm.cmd install
npm.cmd run dev
```

Open the localhost URL printed by Vite (normally **http://127.0.0.1:5173**). On macOS/Linux, use `npm` instead of `npm.cmd`. The `.cmd` form also works in Windows PowerShell when execution policy blocks `npm.ps1`.

```powershell
npm.cmd run build
npm.cmd run preview
```

Vite emits the importer JavaScript and WebAssembly into `dist/assets`. Serve the built `dist` directory over HTTP(S); opening `index.html` as a `file://` URL is unsupported. Use localhost or HTTPS for SHA-256 and UUID browser APIs.

## Using the workspace

1. Choose **Open STEP**, or drop a `.step` / `.stp` file into the page.
2. Drag to orbit, right-drag to pan, and scroll to zoom. **Fit model** keeps the current viewing direction; **Reset view** restores the default direction.
3. Hover to preview a complete face in teal. Click to select it in amber, or choose it from **Browse CAD faces** using the keyboard. Click empty space, choose **Clear**, or press Escape to clear selection.
4. Write a comment and choose **Add comment**. Multiple comments can belong to the same face. Switching faces clears the draft so it cannot be submitted against the wrong face accidentally.
5. Use a comment's face link to select and frame that face. Edit or delete comments using their card controls. Deletion asks for confirmation.
6. Refresh and choose **Reopen project** to restore the last model and its comments. Reopening the exact same file also restores its annotations, even if its filename changed.
7. Use **Export JSON** for a portable annotation backup, and **Import JSON** to merge annotations for the opened model. A matching comment ID is updated by the imported record; other existing comments are retained.

### Boundary conditions

Select a CAD face, choose a type under **Boundary conditions**, enter its values, and choose **Apply to face**:

| Type | Values and conventions | Face visual |
| --- | --- | --- |
| Fixed support | Ux = Uy = Uz = 0 (translations) | Purple face tint and support glyphs |
| Prescribed displacement | Global X/Y/Z components in **mm**; all three are prescribed, including zero | Green tint and resultant-direction arrow; all-zero values use support glyphs |
| Force | Total face force, global X/Y/Z components in **N**; nonzero resultant required | Coral tint and resultant-direction arrow |
| Pressure | Signed **MPa**; positive acts inward, negative outward; nonzero required | Blue tint and distributed arrows along local surface normals |

Conditions remain visible when deselected. Face labels show their types and numeric values and move with the camera. Clicking a condition's face link selects and frames its face. Use **Edit condition** or **Remove condition** to change or delete it. Multiple conditions can be attached to a face; switching faces resets the condition editor to prevent accidental reassignment.

The model is imported in millimeters. Arrows use a readable model-relative size, not magnitude scaling. Glyphs sit on tessellated surface samples, including curved faces; inward arrows end at the surface so they remain visible. Conditions are stored and visualized as project annotations; no finite-element solve or solver-specific boundary-condition deck is generated.

Boundary conditions persist alongside comments under the exact model hash. JSON exports use **schema version 2**, with a `boundaryConditions` array. Version-1 comment-only files still import and preserve existing conditions. Version-2 import validates comments and conditions before writing both in one transaction; missing faces remain unmapped. The IndexedDB version-2 upgrade preserves existing version-1 model and comment data.

## Identity and storage

- `occt-import-js` **0.0.23** imports STEP in a disposable background worker. Starting a newer import terminates the previous worker. A failed replacement preserves the current project.
- `brep_faces.first` and `.last` are **inclusive triangle indices**. Each mesh gets a triangle-to-face lookup. Hover and selection overlays draw the entire corresponding triangle range.
- Keys include hierarchy occurrence path, source mesh index, mesh slot, and original face index. Repeated component names and repeated geometry references remain distinct.
- OpenCascade supplies the imported coordinates; the importer node hierarchy is used for identity. No additional occurrence transform is assumed.
- SHA-256 of the exact uploaded bytes identifies the model version. Different hashes are rejected during annotation import, even when the models look alike.
- IndexedDB stores model blobs, metadata, the last-project reference, and comments indexed by model and face. Writes are immediate; failed writes are reported. Clearing browser site data removes local projects. Export JSON to back up notes; retain the original STEP file separately.
- Boundary conditions have their own IndexedDB store, indexed by model and face, with IDs, type-specific numeric values, and created/updated timestamps.
- JSON imports validate schema, model identity, comment fields, dates, duplicate IDs, and optional anchors before writing. Missing face keys remain visible as **Unmapped face** and are never attached to a substitute face.
- Models and comments are processed locally. Runtime assets are served by the local app; no CAD file is uploaded to a service.

## Project structure

```text
src/
  main.js                    UI, project state, loading and comment workflows
  styles.css                 Responsive layout and focus states
  cad/
    stepImporter.js          Worker lifecycle, WASM asset URLs, SHA-256
    faceMap.js               Validated triangle ranges and occurrence identity
  viewer/
    scene.js                 Three.js scene, camera, picking and face overlays
    boundaryVisuals.js       Whole-face tints, surface samples, support glyphs and arrows
  boundaries/
    conditions.js            Condition types, units, summaries and validation
    panel.js                 Boundary-condition editor and navigation cards
  comments/
    commentStore.js          IndexedDB model/comment transactions
    exportImport.js          Portable JSON validation and export
tests/
  unit.test.js               Identity, mapping and annotation validation
  browser/workflow.spec.js   Real importer and production-browser workflows
```

## Verification

```powershell
npm.cmd test
npm.cmd run build
npx.cmd playwright install chromium
npm.cmd run test:browser
```

Browser tests serve the production build on port 4173. They download the cube and rounded-cube STEP fixtures from the upstream `occt-import-js` test repository, so this test suite needs internet access. The rounded fixture contains cylindrical surfaces; tests verify its multi-triangle face mappings, plus real WebAssembly loading, picking, orbit-drag suppression, CRUD, exact-face association, IndexedDB restore, JSON transfer, invalid files, stale imports, and narrow-screen layout. Boundary-condition coverage includes all four types, visible face annotations, numeric validation, editing/removal, persistence, JSON round-trips, and an actual database upgrade preserving legacy comments. Unit tests verify full-face visual geometry and force/pressure arrow directions.

Large models use native Three.js raycasting; BVH acceleration and benchmarking on large industrial assemblies are future work. Annotation pins are optional in the specification and are not currently drawn. Anchors are preserved in JSON and comment records when available.

## Dependencies

Vite, Three.js, `idb`, and `occt-import-js`. OpenCascade/importer licensing notices are provided in `node_modules/occt-import-js/dist/license.occt.txt` and `license.occt-import-js.txt`; upstream source: https://github.com/kovacsv/occt-import-js.
