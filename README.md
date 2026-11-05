# CAD Simulation Studio

A local-first browser workspace for reviewing STEP CAD models and attaching comments and boundary conditions to **whole original B-rep faces**. Implemented from [`STEP_FACE_COMMENTS.md`](./STEP_FACE_COMMENTS.md).

## Develop on a Mac, run Ansys remotely

Use [`MAC_REMOTE_SETUP.md`](./MAC_REMOTE_SETUP.md) for the local development setup.
The Gradio app supports running its existing Mechanical worker through OpenCode's API,
including private file transfer, job identity checks, and result downloads.
The Mac runs the CAD workspace; the remote Ansys computer does the simulation.
Open **Start Mac App.command** after installing the local dependencies.
The remote portal login and Python/worker paths must be configured before a real
remote simulation can run. No SSH or browser automation is required. The standalone browser-only Vite app does not submit
Mechanical jobs.

## Simulation Studio frontend

For an easy first run, import the included
[`simple-bracket.step`](./examples/simple-bracket/simple-bracket.step).
It has nine faces and one clear mounting face and loading face. Follow the
[guided demo prompts](./examples/simple-bracket/README.md) to highlight, confirm,
and analyze it through the chatbot.

The default app at <http://127.0.0.1:7860/> uses a React interface adapted from
[Zoo Design Studio](https://github.com/KittyCAD/modeling-app), with its Inter font,
color tokens, icons, panel styling, conversation bubbles and composer. The
viewport and chat share the existing simulation state. View controls, face
selection, saved setups, generated Python and results are available from compact
side panels. The frontend does not include CAD modeling or geometry editing.

After frontend edits, run `npm run build:studio` and refresh the app. The backend
must be restarted after Python changes. `scripts/setup-mac.sh` builds both the
Studio frontend and the retained Gradio viewer. Browser checks for Studio run
with `npx playwright test --config playwright.studio.config.js`; their solver
results are explicitly synthetic and do not consume an Ansys license.

Upstream code is pinned to `d01b321d5540cbcc59d8d7941cfb6056bbe1c91b`.
The MIT notice, Inter font license, and a record of adapted files are retained in
[`src/studio/vendor/zoo`](./src/studio/vendor/zoo). Zoo's engine, authentication,
and CAD editing state machines are not part of this integration.

## Chat-driven CAD workspace and MCP

Simulation Studio places the CAD viewer on the left and a simulation chatbot on the
right. Click a face and say “fix this face,” describe a load on another face, and
answer the assistant's questions. The assistant writes actual PyMechanical
Python for the uploaded geometry, executes it remotely, reads errors/results, and
revises its code. It can write mesh-refinement loops and return measured
comparison tables and plots. Generated source and per-attempt artifacts are
visible and downloadable in the chat. Face highlighting and saved conditions
remain connected to the viewer.

The authoritative selection, highlights, face metadata, conditions, analysis
settings, and result status are also available as MCP resources at
`http://127.0.0.1:7860/mcp/`. The built-in chat host uses the same resource state
before each model step and the same validated tools as external MCP clients.
See [Chat and MCP](./gradio_app/README.md) for resource URIs, tools, architecture,
and the supported analysis scope.

The generated-code path supports analyses expressible with the installed
Mechanical **2026 R1 (261)** APIs and license; geometry, material, contacts and
physics still need a valid setup. It is not restricted to steel or a particular
part. The older single-solid steel/static preset is retained separately. The
viewer accepts STEP/STP. Each job has a 15-minute timeout, one CPU, and a
32,000-node/element limit; see the runtime guide for execution boundaries. The Mac uses the model already configured on OpenCode;
see [private connection setup](./MAC_REMOTE_SETUP.md). The standalone Vite app
below remains a local annotation viewer with manual controls.

### Publishing this repository

Virtual environments, dependencies, build outputs, test artifacts, and local
CAD/annotation/simulation data are excluded by `.gitignore`. Keep local interpreter
paths in your shell environment or ignored local configuration, not in committed source files.
Before pushing, review `git status --short` and the staged files. Do not force-add
`gradio-data/` or `test-results/`: their models, databases, reports, and archives
can contain private CAD data and absolute local paths. Custom `--data-dir` or CLI
output directories should be outside the repository or added to `.gitignore`.

## Run the standalone annotation viewer locally

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

## Using the standalone annotation viewer

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
