# Fluent MCP integration

Fluent follows the existing Mechanical **OpenCode MCP registration pattern**:
OpenCode starts the official server as a local stdio process and exposes its
tools to the coding agent. No bespoke MCP implementation or client bridge is used.

## Installed configuration

- Project configuration: `opencode.jsonc` in this deployment and in
  `C:\Users\neoth\Documents\Graduate-Research\Test-env\workspace`.
- Server name: `ansys-fluent`, alongside `ansys-mechanical` in the workspace.
- Interpreter: `.venv-fluent-mcp\Scripts\python.exe`.
- Entry point: `scripts/fluent-mcp-server.py --transport stdio`.
- Dependencies: `requirements-fluent-mcp.txt` (Python 3.12 or newer).

The startup script preloads PyFluent on the main thread before delegating to the
official `ansys.fluent.mcp.server.launcher`. This avoids a Windows native-library
initialization stall observed when API discovery first imports NumPy on a server
worker thread. Starting the MCP server does **not** start Fluent.

Create an equivalent environment with:

```powershell
python -m venv .venv-fluent-mcp
.\.venv-fluent-mcp\Scripts\python.exe -m pip install -r requirements-fluent-mcp.txt
```

Paths in the installed configurations are machine-specific; update the interpreter,
startup script, and `cwd` when moving the deployment. Leave the Mechanical and
Fusion registrations unchanged. Use OpenCode's `/mcps` to inspect connection state.

## Agent workflow

1. Call `session_status` before connecting. Do not launch or take over another
   simulation session just to inspect API documentation.
2. Use `find_api` and help/path-discovery tools before generating unfamiliar calls.
   The offline catalog can differ from Fluent 261; inspect live task arguments
   and allowed values when available. Empty search results are not proof that an
   API does not exist. This installed release may return path-only catalog entries.
3. Call `validate_code` before `run_code`. Offline `parse_ok` is only a syntax/AST
   check, not proof of live API, meshing, geometry, or physics correctness.
4. Inspect state after mutations. In particular, validate mesh import format and
   units, region changes including old-value lists, fluid/solid zone counts, cell
   counts, and boundary correspondence before applying conditions or iterating.
5. Preserve user confirmation, model identity, source CAD, condition scoping,
   resource caps, convergence checks, and recovery-only handling of uncertain jobs.
   MCP availability does not authorize a simulation or bypass these safeguards.

## Scope

### Studio web-chat tooling

Studio now exposes `find_fluent_api`, `get_fluent_api_help`, and
`validate_fluent_api_code` as typed read-only chat actions backed by the same
official server startup over MCP stdio. `FLUENT_MCP_PYTHON` in `.env.local.json`
selects the isolated interpreter. These calls cannot connect/launch a solver or
invoke `run_code`. Provider credentials are not forwarded to that subprocess.

Set optional `FLUENT_MCP_API_OBJECTS_PATH` to the worker's generated
`api_tree/api_objects.json`. The adapter forwards it using the official server's
`FLUIDS_MCP_API_OBJECTS_PATH` setting. This prevents a newer server-default catalog
from incorrectly rejecting paths present in the older worker. The result labels
the catalog source. This is still offline discovery/validation, not a live-release
or physics check; documentation can be unavailable even for indexed paths.

`validate_fluent_program` separately compiles/checks the complete Studio program
against the worker's misuse guards. MCP's sandbox only supplies `solver`/`session`,
not Studio's `ctx`, `tasks`, `meshing`, or `workflow`. Validate the underlying
PyFluent snippets through MCP and the complete wrapper program locally; do not
claim that a local contract check establishes MCP/live compatibility.

`check_fluent_worker` uses the actual configured connection's package/protocol
check without a submission, solver launch, or license checkout. Its compatibility
criteria are shared with execution preflight (PyFluent 0.37.x, worker protocol v2).
These tools appear in both the web agent's action schemas and Studio's MCP facade.
They preserve the current model, revision, annotations and pending confirmations.
No generic mutating MCP proxy is exposed to the web agent.

Restart idle Studio after changing its configuration/code. The native OpenCode
registration and simulation-worker execution flow remain unchanged.

This is the same **coding-agent integration layer** as Mechanical's MCP server.
The Studio web chatbot and remote simulation worker remain separate: their bounded
execution path still uses PyFluent directly, just as the Mechanical worker uses
PyMechanical directly. Registering MCP does not route Studio jobs through MCP.
The independent `.venv-fluent` worker remains on PyFluent 0.37.2; do not install
MCP dependencies into it. No server restart, saved-model migration, or solve is
required for this OpenCode registration.

The initial integration checks through the native `ansys-fluent` tools returned
disconnected session status, API discovery entries and `parse_ok`. Those were
discovery checks, not a successful simulation. A later native-STEP workflow
resolved the earlier face-mapping failure and completed the saved-water run;
see [verified run](fluent/VERIFIED_WATER_RUN.md). The dated
[package verification](docs/VERIFICATION.md) distinguishes those historical
solver results from the latest software checks.
