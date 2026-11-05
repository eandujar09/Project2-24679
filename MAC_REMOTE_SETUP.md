# Mac development with remote Ansys Mechanical

The Mac runs the Gradio CAD workspace. Simulations send the exact STEP model and
saved conditions through the remote OpenCode API over Tailscale, run the fixed
Mechanical worker on Windows, and download the report, contours, and project.
The right panel is a coding agent that gathers the setup and authors PyMechanical
Python for the uploaded geometry. The worker executes that source through the
OpenCode API in a fresh, time-limited Mechanical job; no browser
automation or SSH is required. See [Chat and MCP](./gradio_app/README.md).

## Start and develop locally

Double-click **Start Mac App.command**, then open <http://127.0.0.1:7860>.
The Python environment and Node dependencies are installed in this checkout.
From a terminal in the repository:

```sh
./.venv-gradio/bin/python scripts/run_mac.py
```

Edit Python in `gradio_app/` and the solver in `mechanical/`. Restart the app after
Python changes. After editing the Studio interface, run `npm run build:studio`.
The retained Gradio viewer is built with `npm run build:gradio`.
After changing solver code, deploy it with the command below while no job is running.
The standalone `npm run dev` viewer does not submit Mechanical jobs.

For a fresh Mac checkout, install Python 3.12 and Node.js, then run
`./scripts/setup-mac.sh`. Ansys is required only on the remote Windows computer.

## Private connection settings

The launcher reads `.env.local.json` in the project folder:

```json
{
  "MECHANICAL_TRANSPORT": "opencode",
  "MECHANICAL_REMOTE_DIR": "C:/path/to/project2-mac-worker",
  "MECHANICAL_REMOTE_PYTHON": "C:/path/to/project2-mac-worker/.venv-ansys/Scripts/python.exe",
  "MECHANICAL_REMOTE_PLATFORM": "windows",
  "CAD_CHAT_PROVIDER_ID": "openai",
  "CAD_CHAT_MODEL": "gpt-6.1-sol"
}
```

The remote webpage login is stored separately in `.env.opencode.json`:

```json
{
  "url": "http://REMOTE_TAILSCALE_ADDRESS:PORT",
  "username": "YOUR_PORTAL_USERNAME",
  "password": "YOUR_PORTAL_PASSWORD"
}
```

Both files are ignored by Git. Environment variables override launcher settings;
`OPENCODE_CONFIG` can select a different login file. Credentials stay on the Mac
and are sent only in authentication headers to the configured server. Redirects
and system proxies are disabled for these requests.

The current connection uses OpenCode v2's direct shell and file APIs:
`/api/shell`, `/api/fs/read/*`, and `/api/experimental/fs/write`. The write API is
experimental, so a server upgrade may require updating the client. A portal login
must authorize these APIs; Tailscale membership alone does not grant that access.

The chatbot uses a model already connected to the same OpenCode server through
its transient `/api/session/{id}/generate` endpoint. It gets the conversation and
face metadata, selection, highlights, and saved conditions. Each chat uses its
own session with remote agent tool permissions denied. The local host validates
typed actions, records generated source, and controls the Ansys worker. The model
can write analysis code and revise it from actual runtime errors. Its OpenCode
session itself has no shell/file tools; execution is through the CAD runtime. Model/provider settings may
need changing for another server; a model quota failure appears in the chat.

## Remote environment and deployment

The worker needs Mechanical **2026 R1 (261)**, its license, and
`ansys-mechanical-core==0.12.7`. This computer uses a dedicated `.venv-ansys`
environment based on the Python bundled with Ansys 261. No system Python, Ansys
installation, firewall, or other project's environment is modified.

A Python distribution installed by uv produced an OpenSSL library conflict on
this host. Prefer the Ansys-bundled Python here. See the
[Ansys explanation of the DLL conflict](https://aedt.docs.pyansys.com/version/stable/Getting_started/Troubleshooting.html#error-with-uv-created-virtual-environments-on-windows).

Deploy worker source after changing `mechanical/`:

```sh
./.venv-gradio/bin/python scripts/deploy-worker.py
```

This uploads only the worker source, entry points, and requirements file. It does
not install packages or copy credentials, local models, or the Mac environment.
The configured remote directory and Python environment must already exist.
Optional SSH support is retained for other hosts by setting
`MECHANICAL_TRANSPORT=ssh` and `MECHANICAL_SSH_HOST`; it is not used here.

## Run a simulation

1. Keep Tailscale connected and the remote computer and OpenCode server running.
2. Open a single-solid STEP model and tell the chatbot what you want to test.
3. Click a face, then say “fix this face.” Select a different face and specify its
   load, direction, and units, such as “100 N in global +X.”
4. Establish the material, analysis type and assumptions in chat. For a mesh
   study, ask it to compare mesh sizes and state a convergence criterion.
5. Inspect the Python it generates, then the measured results, comparison table
   and actual images. Download the source and per-attempt ZIP for review.

**Connection → Check remote Ansys connection** remains available below the viewer.
Amber is your selection; violet is an independent assistant highlight. Saved
conditions remain attached to their exact original faces. Reopen a model from
**Saved models** to recover annotations. Chat history and selection belong to
the current browser window and are not restored after a reload/server restart.

Connection checks verify API access and the Python package. An actual successful
solve verifies that Mechanical starts and a solver license is available.
Generated Python chooses the analysis setup; the host limits each solve to one
CPU and at most 32,000 nodes/elements, with a 15-minute job timeout. The older
fixed preset separately requires Structural Steel, small deformation and one
solid. See the [runtime guide](./gradio_app/README.md) for the code execution boundary. A successful run is not
a mesh-convergence or engineering-validity assessment.

## Recover after a dropped connection

Each submission has a unique job ID. The Mac stores its record under
`gradio-data/exports/simulations/`; the remote worker keeps its results under
`worker-data/<job-id>/`. The client saves the command ID before waiting and never
automatically resubmits a solve. Inspect or retrieve a previous job with:

```sh
./.venv-gradio/bin/python scripts/remote-job.py PATH_TO_REMOTE_JOB_JSON
./.venv-gradio/bin/python scripts/remote-job.py PATH_TO_REMOTE_JOB_JSON --fetch
```

The worker serializes its solves with an OS lock, uses a 15-minute solver timeout,
and retains reports and logs on failure. A failed run does not display previous
contours. Model hashes and job identities are checked; archive paths and transfer
sizes are validated. Input is limited to 128 MiB and expanded results to 2 GiB.
A job record contains no login. Recovery requires the same server and credentials
file, or `OPENCODE_CONFIG` pointing to the appropriate private file.

## Checks

```sh
./.venv-gradio/bin/python -m unittest discover -s tests/python -v
npm test
npm run build
npm run build:gradio
npm run build:studio
npm run test:gradio
npx playwright test --config playwright.studio.config.js
```

Automated transport tests use synthetic solver output and local HTTP/subprocess
fixtures. They check binary transfer, authentication, redirect refusal, archive
validation, job identity, concurrency, and recovery state. They do not claim to
validate Ansys physics. Real smoke-test artifacts are retained separately under
`simulation-results/remote-smoke/` in this checkout and are excluded from Git.

### Verified on November 4, 2026

An actual Mac → OpenCode 2.0.32 → Mechanical 261 → Mac run succeeded for a
40 × 10 × 10 mm Structural Steel bar, fixed at one end with 100 N axial force on
the other. The mesh contained 816 nodes and 385 quadratic tetrahedra. Maximum
deformation was 0.000198583 mm and maximum von Mises stress was 1.32662 MPa.
The downloaded report, two contour PNGs, text results, and project archive were
checked. This verifies execution and transfer, not mesh convergence.

The runner now explicitly selects GPU device **None** in addition to setting
zero GPU devices; the remote user's saved NVIDIA setting otherwise prevented
this CPU-only solve. Solver diagnostics are copied before Mechanical closes.
A subsequent real chatbot test used three messages to establish analysis settings,
fix the selected end face, load the opposite selected face, and run Ansys. It
returned the same numerical result and both real contour images. Its local
artifacts are under `test-results/chat-live/` (excluded from Git).

The updated suite passes 56 Python tests and three Gradio browser tests. It
covers generated-code submission, runtime-error correction, safe job recovery,
multi-solid input, per-window isolation, and code/table/image rendering, plus
the chat tool loop, real MCP HTTP resource reads and
highlighting, stale-state rejection, duplicate load/run prevention, and browser
selection/chat/image rendering. Browser and unit fixtures use explicitly marked
synthetic results; the real remote solve above was checked separately.

The generated-code bracket study and its measured convergence comparison are
documented in [Chat and MCP](./gradio_app/README.md#verified-generated-code-bracket-study).
