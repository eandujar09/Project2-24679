# Optional native Fluent graphics

This adapter opens an **existing** `.cas.h5` / `.dat.h5` pair, renders native Fluent boundary-surface contours through MCP, and closes the postprocessing session. It does not iterate the flow or change its physical setup. Studio can run its core simulations and extracted-data plots without this integration.

It is separate from the official `ansys-fluent` API-discovery MCP server and the PyFluent 0.37.x execution worker. Use a dedicated environment; do not install these requirements into either of those environments.

## Dependency and provenance

The renderer is [`cmuchancel/ansys-fluent-mcp`](https://github.com/cmuchancel/ansys-fluent-mcp), pinned at `3ff6cf7b6f2997b5fa0b5f2cd896c7ba1ab2fbc0`. That repository is **private**; reproducing native plots requires authorized access. This package does not redistribute its source. `requirements.txt` records the exact revision and tested runtime packages. It imports `ansys_fluent_mcp`, distinct from the official `ansys.fluent.mcp` namespace.

`server.py` is the project's adapter recovered from the live host. The packaged copy replaces machine-specific absolute paths with the Studio root and its private configuration. The original live host still uses its pre-existing external adapter path. The [deployment audit](../../docs/DEPLOYMENT.md) records this deliberate difference.

## Install on the Windows Ansys host

With Git access to the private dependency and Ansys 2026 R1 installed:

```powershell
py -3.12 -m venv .venv-fluent-post
.\.venv-fluent-post\Scripts\python.exe -m pip install -r integrations\fluent_post\requirements.txt
```

Add these absolute Windows paths to the Studio host's ignored `.env.local.json`:

```json
{
  "FLUENT_POST_PYTHON": "C:/path/to/Studio/.venv-fluent-post/Scripts/python.exe",
  "FLUENT_POST_SERVER": "C:/path/to/Studio/integrations/fluent_post/server.py"
}
```

The adapter finds the Studio root two directories above itself; `STUDIO_ROOT` can override this for direct use outside the repository. It reads `FLUENT_REMOTE_DIR` (or `MECHANICAL_REMOTE_DIR`) from that root's private settings to find the existing worker lock. The adapter and worker must be on the same Windows host and use the **same lock directory**. `AWP_ROOT261` defaults to the standard Windows Ansys 261 installation path.

Restart only an idle Studio process after configuring it. Studio starts the stdio adapter on demand through `fluent/postprocessing.py`; a separately hosted HTTP MCP server is not required. This subprocess must run on the Ansys host. A Mac cannot execute the Windows interpreter path locally.

## Controls and result handling

- Existing matching case/data required; one CPU and one session.
- Holds the shared worker lock, including when solver exit is uncertain.
- Removes the upstream `execute_tui` tool and exposes a narrow `create_contour` operation for pressure or velocity magnitude on verified surface names.
- Studio checks the current job/CAD identity and saved one-to-one face mapping before rendering.
- Native graphics failures remain separate from valid solver results. Never rerun a flow just because rendering failed.
- The views show mapped boundary surfaces. Internal slices are not implemented; no-slip wall velocity is zero.

`test_adapter.py` contains six tests with mocked launches for resource restrictions, missing data, lock exclusion, failed-load cleanup, uncertain-close handling and the tool catalog. [Run instructions and evidence](../../docs/VERIFICATION.md).
