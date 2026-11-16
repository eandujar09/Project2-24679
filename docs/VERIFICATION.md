# Verification record

Package reviewed November 15, 2026. The [machine-readable summary](evidence/verification.json) records commands and outcomes. This separates newly repeated software checks from previously recorded licensed solver results.

## Repeated during packaging

| Check | Result | What it establishes |
| --- | --- | --- |
| Python `unittest` suite | 196 passed | Workspace/state, confirmation, transport/recovery, solver contracts, mapping, thermal conditions and real OpenCascade domain operations |
| JavaScript unit suite | 17 passed | Boundary data, geometry/viewer helpers and frontend logic |
| Studio Playwright suite | 9 passed | Upload, choices, proposals/approval, shared state, synthetic result downloads, camera/visual tools and layout |
| Both frontend production builds | Passed | Source builds with the committed npm lockfile |
| Built files versus live host | Seven of seven SHA-256 matches | Rebuilt frontend is byte-identical to deployed assets |
| Live authenticated browser | STEP imported; nine faces visible | Running server, login, CAD parsing and viewport work together |
| Optional graphics adapter | Six safeguard tests; see summary | Mocked launch/cleanup/locking and narrowed tool catalog, without starting Fluent |

The browser suite uses `tests/serve_chat_fixture.py`: a **scripted agent and synthetic solver responses**, not the model or Ansys. Its generated-domain geometry uses actual OpenCascade. The live import check used a separate fresh session and did not send a chat message or start a solve. No new licensed simulation was run during this package audit.

## Historical engineering evidence

### Mechanical — November 5

[`verified-demo.json`](../examples/simple-bracket/verified-demo.json) records three actual bracket solves at 8, 5 and 3 mm mesh sizes. Each has a `Done` solve record. The recorded 5-to-3 mm displacement change is about 0.152%. Inputs and a walkthrough are in [the bracket example](../examples/simple-bracket/README.md). This is a numerical reference for that setup, not an independent analytical/experimental validation or a universal mesh-convergence claim.

### Fluent — November 12, retrieved November 15

[The report excerpt](evidence/fluent-verified-run.json) was extracted from the saved real host report. It preserves the original report digest, CAD/program hashes, mesh/solve records, measured metrics and limitations. It omits private machine paths and the large logs/residual history; the complete archive remains on the host.

- 18 original faces mapped; one fluid zone; 25,685 cells.
- 929 iterations, residual criterion `1e-5` satisfied.
- Relative mass imbalance `1.7737082582379956e-7`, below `0.001`.
- Native [pressure](evidence/native-pressure.png) and [velocity](evidence/native-velocity.png) images were downloaded from that saved result. These show boundary surfaces, not internal fluid slices.
- This was a host-controlled worker run. It was not presented as a newly completed result in the then-open chat.

The record verifies numerical criteria on one mesh. It does not establish physical appropriateness of the steady-laminar assumption, mesh independence or domain independence. See [run details](../fluent/VERIFIED_WATER_RUN.md).

## Repeat the checks

From the repository root, after installing the [Studio dependencies](SETUP.md):

```sh
npm ci
npm test
npm run build:gradio
npm run build:studio
.venv-gradio/bin/python -m unittest discover -s tests/python -v
npx playwright install chromium
GRADIO_TEST_PYTHON=.venv-gradio/bin/python npx playwright test --config playwright.studio.config.js
```

On Linux, browser libraries may require `npx playwright install --with-deps chromium`. In PowerShell, set `$env:GRADIO_TEST_PYTHON` to the installed Studio Python before running Playwright. The fixture uses port 7862; keep that port free.

The package audit used a separate `.venv-review` with Python 3.12. Replace that path in the evidence commands with your installed environment; it is not a required directory name.

Optional adapter checks, in its isolated environment with the private pinned dependency installed:

```powershell
$env:STUDIO_ROOT = (Get-Location).Path
.\.venv-fluent-post\Scripts\python.exe -m pytest integrations\fluent_post\test_adapter.py -q
```

All Fluent launches in those six tests are mocked. The separate `tests/fluent/test_live.py` and Mechanical live tests require explicit operator setup, real solver software and a license; they are not part of the unlicensed suite above.

## Not established by this package

There is no measured general agent success rate, arbitrary-CAD guarantee, independently verified thermal solve, or end-to-end new live model-to-solver run during packaging. The optional native renderer depends on another private repository. A package/protocol readiness check does not check out an Ansys license. [Limits and next work](LIMITATIONS.md).
