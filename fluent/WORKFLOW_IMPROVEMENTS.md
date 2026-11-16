# Fluent Studio workflow improvements

## Agent execution remains agent-authored

`review_fluent_workflow` is a read-only setup review. It returns saved assumptions,
unassigned original face keys and the native-STEP example source. The agent adapts
and validates its exact program; no worker template or physical default is injected.
Native STEP options must preserve one zone per face in **both** import and surface
generation. Curvature and stabilization settings that worked for the saved-water
case are reference numerical choices, not a universal physical/mesh guarantee.
Guided execution still confirms the actual code; autonomous mode still requires
sufficient user intent. All existing caps, mapping and convergence checks remain.

## Chat reliability

Discovery/help/validation results now reach the model instead of being replaced
with “Applied”. Identical successful read-only inspections are cached only within
the current turn/revision. Errors are not cached. State-changing operations are
never cached or retried by this mechanism.

Results in model context summarize geometry and bound logs/tables. Per-turn
observations are bounded and limited to the latest 12. Full reports, source,
tables and logs remain in artifacts. The successful saved-water report measured
683,403 characters versus 6,753 for the model-visible summary. This reduces prompt
size; it does not prove the cause of any historical provider HTTP 503.

## Native graphics in Studio

After a verified, converged Fluent run **or recovery**, the normal result pipeline
optionally enriches its result with native Fluent images through the separate
`fluent-post` MCP adapter. Typed `render_fluent_results` is also exposed in chat and
Studio MCP for the current completed result. It accepts model/revision only,
not arbitrary case paths. Unknown simulation jobs remain recovery-only.

Before rendering, the bridge checks source CAD hash against the saved request and
report, and verifies that saved geometric face mapping covers the source faces
one-to-one. It opens existing case/data, creates pressure/velocity contours on
those explicit boundary zones, captures native MCP PNG content, closes Fluent,
and includes images in the current result and archive. No solver iteration,
physics assignment or case/data overwrite occurs. Native images appear before
the extra Matplotlib plots, which are explicitly labeled as extracted-data plots.
These are boundary-surface views, **not internal flow slices**; no-slip wall
velocity is zero. An internal-slice helper is not implemented.

Configuration in `.env.local.json` (no credentials):

- `FLUENT_POST_PYTHON`: isolated `.venv-fluent-post` interpreter.
- `FLUENT_POST_SERVER`: the adapter script. The live host uses its original external
  `fluent-post-server.py`; new installations can use the packaged
  [integrations/fluent_post/server.py](../integrations/fluent_post/README.md).

The bridge has a 300-second deadline and a minimal subprocess environment without
chat/provider credentials. The adapter holds the existing worker lock and uses
one CPU. Missing configuration leaves the normal solve/result path unchanged.
A graphics failure is separate from solver convergence; it must never cause an
uncertain simulation status or automatic flow rerun. A timed-out/uncertain post
session is explicitly marked unknown and cannot be automatically retried until
closure is confirmed. The worker lock remains the final exclusion guard.

## Validation

- 196 Python tests; 17 JavaScript tests; 9 Studio browser tests.
- Six post-adapter safeguard tests in the coding workspace.
- A real Studio bridge call rendered the existing converged 25,685-cell case via
  MCP and kept the SHA-256 hashes of both case/data files unchanged. No new flow
  solve was requested, and saved model documents were not changed.

Restart the Studio app after verifying no active/uncertain jobs or pending work;
Python source/config is loaded at process startup. A restart clears in-memory
chat sessions but does not delete saved geometry, annotations, conditions or
result archives. Do not restart OpenCode or its active solver jobs as a shortcut.
