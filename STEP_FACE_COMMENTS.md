# STEP Face Comments — Implementation Specification

## Goal
Build a local-first browser application that loads a `.step` / `.stp` CAD model, allows a user to select an **entire original CAD face** (not merely a rendered triangle), and attach, view, edit, and delete comments on that face.

## Scope and success criteria

### MVP features
1. Upload a STEP file from the user's machine. Drag-and-drop and file-picker upload are supported.
2. Render the model in an interactive 3D viewport with orbit, pan, zoom, reset view, and fit-to-model.
3. Hover over faces to preview selection; click to select one complete CAD face; click empty space or press Escape to clear selection.
4. Show a face's ID in the interface and highlight the selected face distinctly from hover.
5. Add a text comment to the selected face. Require nonempty text. Add created/updated timestamps.
6. List all comments in a sidebar, grouped or filterable by face. Clicking a comment selects its face and focuses the camera approximately on it.
7. Edit and delete existing comments with confirmation for deletion.
8. Persist comments locally across page reloads and enable exporting/importing comments as JSON.
9. Show useful errors for unsupported/corrupt STEP files, importer failure, and missing comment-to-face mappings.

### Non-goals for MVP
- Editing the STEP geometry.
- Multiuser collaboration, accounts, or a cloud database.
- Exact CAD geometry measurements.
- Guaranteeing that comments automatically survive STEP revisions that change topology.

## Proposed stack

- **Vite** with vanilla JavaScript (TypeScript is a recommended alternative).
- **Three.js** for WebGL rendering, camera, orbit controls, raycasting, and overlays.
- **occt-import-js** for STEP → tessellated mesh import with `brep_faces` triangle-to-CAD-face metadata.
- **IndexedDB** for local project data and uploaded STEP file blobs (use a small wrapper such as `idb`, optionally). LocalStorage is acceptable only for tiny comment metadata, not STEP files.
- **three-mesh-bvh** is optional for raycast performance on large models.

Suggested setup:

```bash
npm create vite@latest step-face-comments -- --template vanilla
cd step-face-comments
npm install
npm install three occt-import-js idb
# Optional acceleration:
npm install three-mesh-bvh
npm run dev
```

> The OpenCascade importer uses WebAssembly. Configure Vite to serve the `.wasm` asset correctly, and initialize the importer only after it has loaded. Verify the installed version's actual API and `brep_faces` metadata schema before writing mapping code. Do not assume a face is identical to a single Three.js triangle.

## Screen layout

```text
┌─────────────────────────────────────────────────────────────────┐
│ STEP Face Comments                [Upload STEP] [Fit] [Export] │
├─────────────────────────────────────────┬───────────────────────┤
│                                         │ Selected face         │
│               3D viewport               │ Face: 24              │
│                                         │                       │
│    Hover: subtle highlight              │ New comment           │
│    Click: persistent highlight          │ [Text area         ] │
│    Comment marker: visible dot/pin      │ [Add comment]         │
│                                         │                       │
│                                         │ Comments              │
│                                         │ • Face 24 — ...       │
│                                         │ • Face 8 — ...        │
├─────────────────────────────────────────┴───────────────────────┤
│ Model: bracket.step | 117 faces | 3 comments | Saved locally    │
└─────────────────────────────────────────────────────────────────┘
```

Use accessible labels, keyboard focus indicators, sufficient color contrast, and an alternative sidebar workflow for comment navigation.

## Core architectural rule: preserve CAD face identity

The STEP importer produces triangles for rendering, but face-level selection depends on an explicit relationship:

```text
Imported STEP model
  └── CAD solids / components
       └── original B-rep CAD face ID
            └── one or more rendered triangles
```

For every mesh, construct a lookup from **rendered triangle index** to **CAD face key** based on the importer's `brep_faces` data. The exact range format must be checked against the installed importer version.

Use a namespaced face key to prevent collisions between parts:

```text
faceKey = `${componentKey}:face:${faceIndex}`
```

`componentKey` should be stable for the loaded model where feasible; `faceIndex` is the imported B-rep face index. Preserve importer component/node identity, not just its displayed name. If the imported model contains repeated instances, distinguish occurrences even when they share the same underlying geometry.

**Important:** Face indices can change after modifying or re-exporting STEP files. Bind annotations to an exact model version (e.g., SHA-256 of file contents). Treat annotations from a different file hash as unmapped until explicitly reattached. Do not silently apply comments to a different face.

## Data model

```ts
type ModelRecord = {
  id: string;            // SHA-256 hex of uploaded STEP file
  filename: string;
  importedAt: string;    // ISO timestamp
  fileBlob: Blob;        // IndexedDB only
};

type FaceComment = {
  id: string;            // crypto.randomUUID()
  modelId: string;       // matches ModelRecord.id
  faceKey: string;       // e.g. occurrence-0:face:24
  text: string;
  createdAt: string;
  updatedAt: string;
  // Optional: last selected 3D anchor point for showing comment pin
  anchor?: [number, number, number];
};
```

Store comments indexed by `modelId` and `faceKey`. An anchor is a visualization convenience and must never replace the face key as the authoritative association.

Export schema (portable JSON):

```json
{
  "schemaVersion": 1,
  "modelId": "<sha256-of-step-file>",
  "filename": "bracket.step",
  "comments": [
    {
      "id": "<uuid>",
      "modelId": "<sha256-of-step-file>",
      "faceKey": "occurrence-0:face:24",
      "text": "Check the mounting surface finish.",
      "createdAt": "2026-10-26T16:00:00.000Z",
      "updatedAt": "2026-10-26T16:00:00.000Z"
    }
  ]
}
```

## Implementation stages

### 1. Scaffold and UI
- Create a Vite app and layout with toolbar, 3D viewport canvas, right sidebar, and status area.
- Add hidden file input, drag-and-drop target, loading/progress state, and error banner.
- Keep the interface responsive: sidebar stacks below the viewport on narrow screens.

### 2. STEP import
- Accept only `.step` and `.stp` file extensions in the picker, but handle invalid content gracefully.
- Read the file as an `ArrayBuffer` / `Uint8Array`, initialize the importer, and import with a worker if feasible to avoid freezing the UI.
- Build indexed `THREE.BufferGeometry` with positions, normals, and triangle indices supplied by the importer.
- Maintain metadata needed to identify the model, instance/component, and original face for each triangle.
- Fit the camera using the aggregate model bounding box; update clipping planes for very small/large objects.
- Dispose old geometries/materials/event listeners when replacing models.

### 3. Face picking and highlighting
- On pointer movement, convert pointer location to normalized device coordinates and `THREE.Raycaster`-intersect the model meshes.
- `intersection.faceIndex` identifies the hit triangle **within its Three.js geometry**. Translate that to the corresponding original CAD face using your per-mesh lookup.
- On hover, highlight *every triangle belonging to the original face* (e.g., a dedicated overlay mesh, face-specific draw group/material, or shader mask).
- On click, persist the selected `faceKey`; display it in the sidebar.
- Ensure click selection does not trigger on orbit drags (use a movement threshold).
- On selection change, remove old highlighting and redraw; do not duplicate geometry on every pointermove.
- Clear on empty click or Escape. Keep hover and selection states independent.

Illustrative pseudocode (the importer mapping is application-defined):

```js
const intersections = raycaster.intersectObjects(pickableMeshes, true);
const hit = intersections[0];
if (hit) {
  const { triangleToFaceKey } = hit.object.userData;
  const faceKey = triangleToFaceKey[hit.faceIndex];
  selectEntireCadFace(faceKey);
} else {
  clearSelection();
}
```

### 4. Comments
- Enable the composer only when a face is selected.
- Save trimmed, nonempty comments with UUID and timestamps.
- Display a comment count for each face and all comments in the sidebar.
- When a comment is clicked, select its associated face, zoom/frame the face bounding box (or approximate center), and open its details.
- For the optional 3D pin, place it at the stored raycast hit position; hide or reposition it safely if absent.
- Support edit/delete and persist changes immediately.

### 5. Persistence
- Calculate the uploaded file's SHA-256 with `crypto.subtle.digest` (available on localhost / secure origins).
- Save the file blob and model metadata in IndexedDB so refresh can reopen the project. Offer to reopen the last project; optionally auto-restore if the stored file is accessible.
- Save each comment under the exact `modelId`.
- Implement JSON export using `Blob` + object URL and import using file picker.
- On imported JSON, verify `schemaVersion`, type/field validity, and that `modelId` matches the opened STEP; otherwise show a warning and block automatic mapping.
- Escape user-entered strings by using `textContent` or safe framework rendering rather than `innerHTML`.

### 6. Resilience and performance
- Cancel or ignore stale import results if a second file is selected while importing.
- Report loading state and display actionable errors if WebAssembly cannot load or memory is exhausted.
- Consider `three-mesh-bvh` if native raycasting becomes slow.
- Keep multiple CAD assemblies and large STEP files in mind; benchmark with representative examples.
- Use `ResizeObserver` to resize the renderer and update the camera aspect ratio.
- Set a reasonable pixel ratio limit and release WebGL resources when no longer needed.

## Suggested files

```text
step-face-comments/
├── index.html
├── package.json
├── public/                   # optional served wasm assets
└── src/
    ├── main.js               # application wiring and state
    ├── styles.css            # layout and interaction styles
    ├── cad/
    │   ├── stepImporter.js   # importer setup + STEP to meshes
    │   ├── faceMap.js        # triangle → original faceKey
    │   └── modelIdentity.js  # hash + component occurrence IDs
    ├── viewer/
    │   ├── scene.js          # renderer, camera, lights, controls
    │   ├── selection.js      # hover/click raycast logic
    │   ├── highlighting.js   # full CAD-face overlays
    │   └── markers.js        # optional annotation pins
    ├── comments/
    │   ├── commentStore.js   # IndexedDB CRUD
    │   └── exportImport.js   # JSON transfer + validation
    └── ui/
        ├── toolbar.js
        ├── sidebar.js
        └── status.js
```

## Acceptance tests

- [ ] A valid STEP file renders without requiring a server-side upload.
- [ ] The user can orbit, pan, and zoom without accidentally adding a comment.
- [ ] Clicking one triangle in a curved cylindrical CAD face highlights the **entire cylindrical face**, not just a triangle.
- [ ] Two adjacent CAD faces remain independently selectable.
- [ ] An assembly with multiple parts has no face ID collisions.
- [ ] A comment is always attached to the face selected at submission time.
- [ ] Multiple comments can exist on one face.
- [ ] Clicking a comment highlights the correct face.
- [ ] Edit and delete work and update the visible UI immediately.
- [ ] Refreshing the page and reopening the same STEP file restores comments.
- [ ] Importing annotation JSON for a different STEP hash does not silently attach comments incorrectly.
- [ ] Invalid files and failed imports produce understandable error messages.
- [ ] The UI is usable on desktop-sized screens and keyboard focus is visible.

## Build order

1. Display one STEP file and orbit it.
2. Verify triangle-to-B-rep-face metadata from the importer on a simple test cube and cylinder.
3. Implement complete-face hover and click highlighting.
4. Add the comment editor and list, with in-memory state.
5. Add IndexedDB storage and model hashing.
6. Add export/import, error handling, and automated tests.

## Useful references

- Three.js documentation: https://threejs.org/docs/
- Three.js Raycaster: https://threejs.org/docs/#api/en/core/Raycaster
- occt-import-js: https://github.com/kovacsv/occt-import-js
- Vite: https://vite.dev/guide/
- IndexedDB: https://developer.mozilla.org/en-US/docs/Web/API/IndexedDB_API

## Future enhancements

Threaded discussions, user identities, resolved/open statuses, screenshots, measurement tools, selectable edges/vertices, backend sharing, and robust annotation migration across CAD revisions.
