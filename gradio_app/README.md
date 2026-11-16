# Chat-driven CAD workspace

For the current package, start with [architecture and tool flow](../docs/ARCHITECTURE.md)
and [setup](../docs/SETUP.md). This reference retains the detailed Mechanical and
shared-workspace contracts. The deployed app also includes [Fluent](../fluent/README.md),
[thermal/domain preparation](../HEAT_TRANSFER_AND_DOMAINS.md), official API discovery
and optional native graphics; see the root documentation index.

Start the Mac app with `../Start Mac App.command` or, from the repository root:

```sh
npm run build:studio
./.venv-gradio/bin/python scripts/run_mac.py
```

Open <http://127.0.0.1:7860>. Setup and remote worker deployment are described in
[MAC_REMOTE_SETUP.md](../MAC_REMOTE_SETUP.md).

The root page serves the Zoo-derived React frontend in `src/studio`; its HTTP
adapter is `gradio_app/studio.py`. Both it and the retained Gradio API use the
same `ChatWorkspace`, `ChatAgent`, confirmation gate, and MCP server. The adapter
provides per-window sessions, CAD upload/selection, background chat turns,
pollable snapshots, and scoped result downloads. It does not execute engineering
tools directly. The Confirm button is bound to the exact pending proposal;
message retries use request IDs to avoid duplicate execution. Chat sessions
survive a page refresh while this process runs; saved CAD and conditions survive
a server restart. New conversation preserves saved conditions and job records.

Import CAD always starts a new, empty setup, even for an identical STEP file.
Choose Saved Models to resume previous supports, loads and comments. Each import
has an independent setup ID; portable annotations and Mechanical requests still
use the exact CAD SHA-256, so face mapping and file integrity checks are unchanged.

In Guided mode, proposed supports and loads appear in the viewport before approval,
with a dashed “Proposed” label and the actual support glyph or force/pressure arrow.
Confirmation stays in chat. These previews are session-only and excluded from saved
conditions, exports and solver inputs. Rejection or a changed setup clears the preview;
confirmation replaces it with the applied graphic. Editing a condition previews its
replacement without drawing a duplicate of the existing arrow.

Proposing a face also centers the camera and smoothly rotates toward a visible
side of that face. Curved surfaces use visibility checks, including looking through
hole openings. Small targets retain some surrounding model context. Dragging cancels
the motion; normal polling does not move the camera again. Chat confirmation and
the user's selected face remain independent of camera movement.

## Native Mechanical exports

The project menu and left toolbar offer two downloads, both disabled for a new
CAD import until an appropriate setup or result exists:

- **Export setup (.mechdat):** available after material/analysis settings are
  confirmed, or after the agent creates an analysis in Mechanical. Before a run,
  it builds the confirmed setup without generating a mesh or solving. After a
  generated run, it exports that actual Mechanical model, preserving custom
  analyses, materials and mesh controls. Unconfirmed proposals are excluded.
- **Export solved simulation (.mechpz):** available when a successful current run
  produced a Mechanical archive. The archive includes result/solution and user
  files, so it can be restored in Mechanical with its solver results.

The setup file alone does not bundle external solver results. Setup changes
invalidate current run downloads. Older jobs without native exports must be
prepared/run again; they are never silently replaced with a generic analysis.
The existing simulation ZIP remains available for code, plots and diagnostics.

## Interaction

Open a STEP file, click a whole CAD face on the left, and describe the analysis in
the conversation on the right. The assistant asks for missing information, can highlight or frame candidate
faces, and writes real PyMechanical Python for the current CAD and requested
analysis. It can inspect the Mechanical object model, build analyses, change mesh
controls, solve, export results, and revise its code from execution errors. A click is automatically reported to the assistant when it has asked you
to select a face. Otherwise, your next message includes the latest selection.

Example:

1. “This is Structural Steel. I want a linear static, small-deformation test.”
2. Select the supported face: “Fully fix this face.” Review the violet highlight and explanation, then reply “Confirm.”
3. Select the loaded face: “Apply a total 100 N in global +X.” Check the face, units and direction, then confirm.
4. Ask for an analysis. Review its assumptions and proposed Python, then confirm that execution separately.

The composer has two independent controls:

- **Assistant mode:** Guided simulation (default) pauses for confirmation.
  Autonomous simulation identifies faces, applies the requested setup and runs
  generated code without per-action approval. It can still ask for missing or
  ambiguous engineering intent. Switching modes cancels any pending proposal;
  switching alone never runs it. Code and run records remain visible in both modes.
- **Visual assistance:** off by default. When enabled, the agent receives a CAD
  viewport screenshot at the start of each turn and can request another angle.
  Looking does not require clicking. It can also pick a screenshot pixel to get
  and highlight the exact visible CAD face. This affects only the CAD viewer;
  it does not control the desktop or change the user's selection.

Both settings belong to this browser session and survive refresh while the app
runs. A new session after a server restart returns to Guided with visuals off.
The existing geometry-only workflow is available with visual assistance off.

In Guided mode, the built-in chat requires a later user confirmation before applying settings,
conditions or notes, removing conditions, or executing any Python or preset solve.
This includes inspection scripts and corrected code after an error. A model reply,
tool result or face click cannot approve a proposal. Corrections and questions
discard the pending approval; changing the selection or setup invalidates it.
Highlights can be shown immediately so the user can review the proposed face.
The model is instructed to distinguish observed geometry from inferred purpose,
explain uncertainty, and ask about engineering assumptions in short stages.

Amber indicates the user's selected face. Violet indicates assistant highlights;
highlighting never changes the selection. Support symbols and load arrows remain
visible as saved conditions. The optional face-number picker supports keyboard
selection. The generated Python appears in the conversation before execution. Each attempt
returns actual stdout/errors, verified solve status, measured result tables,
contour images, the Python source, and a downloadable project archive. For a
mesh-convergence request the agent writes the refinement loop and comparison
calculations; there is no hardcoded bracket analysis or mesh-study template.

## MCP interface

The app mounts an official Python SDK Streamable HTTP MCP server at:

```text
http://127.0.0.1:7860/mcp/
```

It binds to loopback by default. The [Windows deployment](../VM_HOSTING.md) binds
to its private Tailscale address and requires authentication on all routes.
Any authenticated MCP client connected to that endpoint can read and control the app.
It does not connect to other Codex/ChatGPT clients automatically.
The chat confirmation gate applies to the built-in conversation. Direct MCP tool
calls are trusted-controller operations and execute after validation; external
clients must implement their own user-confirmation workflow.

Resources:

| URI | Contents |
| --- | --- |
| `cad://sessions` | Open app sessions and their context URIs |
| `cad://models` | Saved CAD models available to open |
| `cad://runtime` | Generated-Python runtime API and resource limits |
| `cad://session/{session_id}/context` | Model ID, revision, selected face, highlighted face keys, geometry descriptors, saved conditions/comments, analysis settings, missing inputs, and result status |
| `cad://session/{session_id}/faces/{offset}` | A page of 100 exact face descriptors, for larger models |
| `cad://session/{session_id}/viewport` | Latest current PNG screenshot, available when visual assistance is on |

Read the context before each action. Resources are read on demand; this version
does not advertise subscriptions or push resource-change notifications. The
built-in chat host includes a fresh snapshot of the same resource state in every
model request. The viewer polls state revisions to reflect external MCP changes.

External MCP clients can use `open_saved_model(session_id, model_id, revision)`
to open a saved model in a chosen window. This resets its conversation, so stale
revisions and switches during an active chat/solve are rejected.

The primary execution tool is `run_mechanical_code(session_id, model_id, revision,
title, objective, code)`. It executes the exact generated source in a fresh
Mechanical job. It needs an uploaded model; it does not require the legacy
steel/static setup. An inspection script can run without any loads.

Other tools: `highlight_faces`, `set_analysis`, `apply_condition`, `remove_condition`,
`add_comment`, and `run_simulation`. Each requires `session_id`, the current
`model_id`, and current `revision`, plus its tool-specific fields. Highlighting
accepts `face_keys` and optional `focus`; an empty list clears highlights.
`apply_condition` accepts `kind`, `face_key`, `values`, and an optional `record_id`
when editing. Force/displacement values use global `x`, `y`, `z`; pressure uses
`magnitude`. Units are mm, N, and MPa, with positive pressure inward.

Visual tools on this same server:

- `capture_viewport(session_id, model_id, revision, view="current")` returns an
  image, frame ID and pixel dimensions. Views: current, iso, top, bottom, front,
  back, left and right.
- `pick_viewport_face(session_id, model_id, revision, frame_id, x, y)` casts a ray
  from that screenshot's frozen camera and maps its visible triangle to the
  original CAD face key. Coordinates are image pixels from the top-left; device
  pixel ratio and later camera movement do not change that mapping. A background
  pixel returns no face. Changed geometry/setup or an expired frame requires a
  fresh screenshot.

Visual calls require Visual assistance enabled and the corresponding Studio tab
open to render the image or perform the pick. They time out if the browser does
not respond. Screenshots contain only the rendered CAD viewport, not the desktop
or chat. The text-only OpenCode generation route remains unchanged when no image
is attached. Image calls use OpenCode's image-capable prompt route with the same
configured model and all native OpenCode tools denied; the CAD host executes the
returned action objects. Images are sent to that configured model provider.

The server rejects stale revisions, unknown faces, unsupported physics,
conflicting conditions, accidental duplicate loads, and incomplete simulations.
Identical consecutive solver submissions are not automatically repeated. A
changed setup clears its current result; old images remain labeled as historical
input snapshots in the chat. Dropped jobs can be recovered using the documented
`remote-job.py` helper.

## Model and solver boundary

`chat_agent.py` sends the conversation, current CAD state, runtime guide, and prior
tool outputs to the model already configured on OpenCode. The model proposes
Python in `run_mechanical_code`; it is not selecting a fixed analysis template.
The local host validates the revision, syntax and size, saves the exact source,
and submits it through the existing authenticated transport. The remote worker
starts a fresh PyMechanical App, imports the exact STEP, attempts exact face
mapping, and executes the source with Mechanical globals plus `ctx` helpers.

The helpers provide face selections, mesh/solve resource checks, measured result
extraction, viewport images, comparison tables, and artifact paths. The script
itself creates the analysis and chooses material, boundary conditions, meshing,
results and refinement logic. It can inspect public Mechanical members at
runtime. No analysis type or material is preselected by this execution path.

The agent reads actual errors and may revise its source up to three attempts per
user turn. Identical submissions are deduplicated; an uncertain transport job
blocks further submissions in that conversation until recovered. The
`recover_mechanical_run` tool checks/downloads that existing job without executing
new code; the agent can invoke it directly from chat. A successful
Python process and a successful solver run are reported separately. Every
attempt has its own source, input snapshot, log, report and project archive.

Execution uses a separate process with a 15-minute limit, one CPU, no GPU, and a
32,000-node/element cap per solve. Basic source checks reject system/network
imports, direct file I/O, private Python access, nested scripts and unchecked
Solve calls. Use `ctx.solve` and artifact helpers. **These checks are not a
security sandbox:** Mechanical has a broad object model and execution uses the
remote worker account's permissions. The model is instructed to operate only on
the current fresh job, never other files/projects. Provider credentials are not
included in the model prompt or job archive.

The model sees CAD metadata and conversation/annotations. The STEP file and
model-authored code go to the configured remote worker. The viewer currently
accepts STEP/STP, not every native CAD format. Arbitrary STEP geometry may be
inspected; multi-body contacts, materials, shell thicknesses and physics still
need valid code, suitable assumptions, and the installed solver/license. Where
cross-kernel mapping is ambiguous, clicked-face scoping fails explicitly; the
agent must inspect or ask rather than invent a mapping.

The previous single-solid/Structural-Steel/static solver remains as the optional
`run_simulation` preset. Its `set_analysis` fields and `legacyPreset` context
requirements apply only to that preset. The chatbot now defaults to generated
Python and does not silently fall back to the preset.

Per-window chat, selection and attempt summaries live in memory. CAD uploads,
annotations and all job files persist under `gradio-data/`. Reopen a saved model
after refreshing; historical job folders and recovery records remain available.

## Development and checks

Python OpenCascade owns CAD identity and geometry. The Three.js viewer reuses the
same canvas while selection/highlights/conditions update. After viewer changes:

```sh
npm run build:gradio
```

Restart the app after Python changes. Chat/MCP/UI changes require no remote worker
deployment. Solver changes require deploying `mechanical/` as described in the
Mac setup guide.

```sh
./.venv-gradio/bin/python -m unittest discover -s tests/python -v
npm test
npm run build:gradio
npm run test:gradio
```

The browser suite runs a separate fixture server on port 7862 with a deterministic
test model and images explicitly marked SYNTHETIC UI TEST. It checks selection, generated Python display/source download, comparison tables,
MCP resource synchronization, independent highlights, supports/loads, result
images, and canvas preservation. The Python suite exercises real MCP HTTP calls
and chat/solver validation. A separate live OpenCode-model-to-Ansys test was
verified on November 4, 2026; details are in the Mac setup guide.

### Verified generated-code bracket study

On November 4, 2026, the connected OpenCode model wrote a fresh bracket analysis
and mesh-refinement loop, and Mechanical 261 executed all three meshes:

| Element size (mm) | Nodes | Elements | Maximum displacement (mm) | Maximum stress (MPa) |
| --- | ---: | ---: | ---: | ---: |
| 6.0 | 7585 | 4182 | 0.0181027 | 29.1558 |
| 4.5 | 9128 | 5053 | 0.0181910 | 28.8158 |
| 3.5 | 11711 | 6556 | 0.0182576 | 30.2797 |

The final stress change was 5.0802%, so the 5% joint displacement/stress criterion
was not met. After a result-transfer interruption, the model used the recovery
tool to retrieve the same job without another solve and correctly reported
non-convergence. This was a live model/solver test; browser fixtures are separate
and explicitly synthetic. Source, actual tables and images are saved in the
workspace's `outputs/bracket-agent-demo/` deliverable folder.
