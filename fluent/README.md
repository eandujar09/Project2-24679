# Agent-authored Fluent integration

Fluent follows Mechanical's existing agentic worker design:

**upload → chat → authored code proposal → exact confirmation → isolated worker
job → measured results**, with shared transport, fingerprints, uncertain-job
recovery, source/log retention and result presentation. The built-in chat does not
require a fixed CFD setup card or complete UI boundary annotations to author code.
Absent values must be agreed in the proposal, never silently assumed.

## What the worker does—and does not do

Like Mechanical's fresh CAD import, the Fluent worker imports the exact source
geometry into a fresh Fluent 261 session. It provides `ctx`, the live `meshing`
session, `workflow` and `tasks`, with face-partitioned STL already imported as Mesh
in millimeters. It supplies **no surface sizing, volume fill, models, materials,
boundary conditions or initialization template**. The submitted Python owns those
choices. The old `ctx.mesh()`/`ctx.configure()` path has been removed, not retained
as a fallback. Historical source and results remain untouched.

The agent can inspect APIs, author setup, use loops/calculations and request real
results, as with `run_mechanical_code`. Inspection-only Python can succeed with
zero `verifiedSolves`; that does not represent a solved CFD analysis. See
[`program.py`](program.py) for the complete runtime guide. The illustrative
[`examples/fluent-channel.py`](../examples/fluent-channel.py) explicitly authors
a particular laminar channel analysis; it is never injected or rendered by the worker.

Shared-style helpers:

| Helper | Role |
| --- | --- |
| `ctx.geometry`, `ctx.analysis`, `ctx.conditions`, `ctx.selected_face` | Exact CAD and optional saved input data, not applied physics |
| `ctx.describe(obj)` | Public API inspection |
| `ctx.update_regions()` | Optional CAD-volume-based fluid-region selection; no physics or sizing defaults |
| `ctx.generate_mesh()` | Execute the agent-configured volume task, switch session, check resources and CAD mapping |
| `ctx.selection(keys)` | Resolve original face keys to verified Fluent zone names |
| `ctx.solve(...)` | Resource-checked iteration with measured residual and mass-balance checks |
| `ctx.record`, `ctx.table`, `ctx.capture` | Real metrics, CSV/JSON, pressure/velocity boundary plots |
| `ctx.save_case`, `ctx.artifact` | Job-local native exports and artifact paths |

The native OpenCode Fluent MCP registration parallels Mechanical's MCP registration;
see [`FLUENT_MCP.md`](../FLUENT_MCP.md). It supports the coding agent's API discovery,
inspection and validation. Studio execution remains direct-worker execution for
**both** solvers, as explicitly selected for this parity migration—not MCP execution.

## Geometry, assumptions and limits

- Fluent 2026 R1 / 261, dedicated worker PyFluent 0.37.x, one CPU, 15-minute job
  process deadline, 32,000 cells before iteration, 2,000 total requested iterations
  per job. These caps are not a peak meshing-memory bound.
- The current checked helper handles **steady flow in one fluid cell zone with no
  solid cell zones**. It does not implement transient stepping, multi-region CHT or
  automatic FSI. Agent-authored physics is not a blanket validation of every Fluent
  feature or engineering assumption. Mechanical remains independent.
- The CAD must be a closed fluid-volume solid, not an obstacle treated as fluid.
  Use the existing confirmed box/cylinder construction/subtraction workflow, or
  separately prepare unsupported custom/internal-passage domains. See
  [`HEAT_TRANSFER_AND_DOMAINS.md`](../HEAT_TRANSFER_AND_DOMAINS.md).
- Surface/volume controls are authored. No automatic tetrahedral or poly-hexcore
  fill, mesh coarsening, implicit wall assignment or hidden hybrid initialization
  remains. Explicit `VolumeFill` is required before `ctx.generate_mesh()`.
- `ctx.update_regions()` expects the authored Describe Geometry step to initialize
  enclosed regions as fluid. It selects the unique 1%-tolerance CAD-volume match,
  marks others dead, and supplies both old and new region lists. It never selects
  by face label or largest volume. Ambiguity stops the operation.
- Face mapping still requires unique trimmed-face forward/reverse sampled distance
  and 2% area agreement. Default distance tolerance is 0.08 mm, configurable up to
  0.1 mm. Split/merged/ambiguous mappings fail; labels, numeric IDs and traversal
  order are not substitutes for verification. Finite sampling is not topology proof.
- Existing saved laminar analysis and SI conditions remain binding user data and
  are read back before solving, but are never automatically applied. That optional
  card is not a generic-physics prerequisite. The authored proposal must specify
  all otherwise missing material, physics, boundary and numerical assumptions.
- `ctx.solve` checks all active residual equations, rather than a hardcoded laminar
  list. Its residual and mass-balance tolerances and iteration budget must be
  explicit or present in saved inputs. Initialization is agent-authored. Multiple
  checked solves are allowed within the total job budget; stale history is rejected.
- Mass balance uses signed integrals over all specified open boundary zones:
  `abs(sum(flux)) / (sum(abs(flux))/2)`. Missing data and nonconvergence fail. Numerical
  convergence does not establish laminar suitability, domain or mesh independence.

UI face conditions retain their SI contract: velocity inlet global x/y/z m/s,
pressure outlet gauge pressure Pa, stationary no-slip wall and symmetry empty
values. Structural pressure remains MPa and is not a CFD outlet pressure.

## Deployment and migration

Install `requirements-fluent.txt` into the dedicated worker interpreter. Do not
install the newer MCP dependencies there; `.venv-fluent-mcp` is independent.

```json
{
  "FLUENT_REMOTE_DIR": "C:\\path\\to\\worker",
  "FLUENT_REMOTE_PYTHON": "C:\\path\\to\\fluent-venv\\Scripts\\python.exe"
}
```

These optional ignored `.env.local.json` overrides otherwise fall back to
`MECHANICAL_REMOTE_DIR`/`MECHANICAL_REMOTE_PYTHON`. Transport is the same authenticated
OpenCode API or SSH worker transport used for Mechanical. No provider credentials
belong in generated code or job archives.

Deploy with `python scripts/deploy-worker.py --solver fluent`. New submissions
require `fluentWorkerProtocol: 2`, and schema-3 requests carry
`executionMode: "agent-authored-v2"`; older fixed-template workers and programs are
rejected before submission. Update the Studio host and worker together. Restart
Studio only while idle to load the new runtime instructions; saved geometry and
conditions require no migration. Reauthor old proposals; do not rewrite archived jobs.

Pre-submission failures remain `not_submitted`/retryable. Once remote execution may
have started, recover the **same job**; absence of a record alone never authorizes
a duplicate solve. Confirmation, source identity and recovery behavior are shared
with Mechanical and have not been bypassed for Fluent.

The normal simulation ZIP retains exact submitted Python, input snapshot, STEP/STL,
actual setup, region controls, mapping evidence, logs, measured histories and
native `case.cas.h5` (plus `case.dat.h5` after iterations). Mechanical-specific
native export menus remain Mechanical-specific. Source checks are misuse guards,
not an OS sandbox; authenticated controller access must remain trusted.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/python -q
npm.cmd test
# Optional licensed synthetic-channel test; never uses the user's CAD:
$env:FLUENT_TEST_PYTHON = (Resolve-Path .\.venv-fluent\Scripts\python.exe).Path
.\.venv\Scripts\python.exe -m unittest discover -s tests/fluent -v
```

The parity migration was checked with synthetic authored meshing: 1,107 cells,
six verified faces, native case export and zero verified flow solves. Unit tests
and meshing checks are not evidence of an end-to-end converged flow simulation.
The later saved-model run resolved face correspondence using authored native STEP
import with per-face CAD zones and curvature refinement, and converged under the
unchanged criteria. See [the measured run and working settings](VERIFIED_WATER_RUN.md).

Studio now exposes a read-only workflow review and optional native postprocessing
through the new MCP server, with bounded chat diagnostics. See
[workflow improvements and configuration](WORKFLOW_IMPROVEMENTS.md).

The operator confirms working Mechanical and Fluent licenses. Revisit licensing
only upon a new explicit launch failure. Capability `licenseStatus: "not_checked"`
means no checkout was attempted, not a licensing blocker.
