# Setup and reproduction

Use the demo branch. This repository does not bundle Ansys, licenses, model-provider accounts, credentials, virtual environments or the live CAD database.

## Mac development

Prerequisites: Git, Python 3.12, and Node.js 20.19+ or 22.12+ (Node 24 also works). Use Python 3.12 for the documented Studio setup. The solver can use its own compatible Python on Windows.

```sh
git clone --branch feat/simulation-studio-demo https://github.com/eandujar09/Project2-24679.git
cd Project2-24679
./scripts/setup-mac.sh
cp config/local.example.json .env.local.json
cp config/opencode-login.example.json .env.opencode.json
chmod 600 .env.local.json .env.opencode.json
```

Edit the two private JSON files. Set the real OpenCode address/login, worker directory/interpreters, and a model/provider already available on that OpenCode server. Optional Fluent settings can be omitted until configured. The startup script does not load `.env.example` automatically; it reads `.env.local.json`.

```sh
.venv-gradio/bin/python scripts/run_mac.py
```

Open `http://127.0.0.1:7860/`. A port can be supplied with `--port 7861`. Rebuild `npm run build:studio` after Studio UI edits and `npm run build:gradio` after shared/retained viewer edits. Restart Studio after Python changes while it is idle.

## Review without model or solver access

The repository includes a deterministic fixture for inspecting the UI and running checks without an OpenCode account or Ansys license. Do not use its outputs as engineering evidence:

```sh
python3.12 -m venv .venv-gradio
.venv-gradio/bin/python -m pip install -r requirements-gradio.txt
npm ci
npm run build:gradio
npm run build:studio
.venv-gradio/bin/python tests/serve_chat_fixture.py test-results/reviewer-fixture --studio
```

Open `http://127.0.0.1:7862/` and import the included bracket. This fixture recognizes scripted requests such as `Fix the back face` and `Compare mesh sizes`. Images/files are marked synthetic; it is not the live AI model or solver. [Full checks](VERIFICATION.md#repeat-the-checks).

## Windows host

Use dedicated environments; do not mix solver dependencies with the official Fluent MCP environment. The tested solver release is Ansys **2026 R1 / 261**.

| Environment | Install | Purpose |
| --- | --- | --- |
| Studio, Python 3.12 | `requirements-gradio.txt` | Web app, OpenCascade and MCP facade |
| Mechanical worker | `requirements-mechanical.txt` | PyMechanical 0.12.7 and installed licensed Mechanical |
| Fluent worker | `requirements-fluent.txt` | PyFluent 0.37.x and installed licensed Fluent |
| Optional API discovery, Python 3.12+ | `requirements-fluent-mcp.txt` | Official Fluent MCP 0.8.0 / PyFluent 0.43.0 |
| Optional native graphics | `integrations/fluent_post/requirements.txt` | Separate private renderer dependency and adapter |

Example Studio installation in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-gradio.txt
npm.cmd ci
npm.cmd run build:gradio
npm.cmd run build:studio
```

Create the solver environments separately and install their respective requirements. On the current Mechanical host, the Ansys-bundled Python avoids a previously encountered Windows DLL conflict; see [Mac/worker setup](../MAC_REMOTE_SETUP.md). Ansys itself must already be installed and licensed.

Populate private `.env.local.json` and `.env.opencode.json`. For non-loopback hosting, the launcher requires authentication:

```powershell
.\.venv\Scripts\python.exe scripts\run_vm.py --host YOUR_TAILSCALE_IP --port 7860 --auth-config .env.opencode.json
```

Tailscale access and the application/API login are separate requirements. The current deployment uses OpenCode v2's authenticated `/api/shell`, `/api/fs/read/*` and `/api/experimental/fs/write` APIs; a server upgrade can require transport changes. No SSH setup is required for this deployment.

## Worker deployment

After configuring absolute worker/interpreter paths and installing packages on Windows:

```sh
.venv-gradio/bin/python scripts/deploy-worker.py
.venv-gradio/bin/python scripts/deploy-worker.py --solver fluent
```

Run only when the worker is idle. These copy worker source; they do not install Ansys, environments or licenses. `check_fluent_worker` and the app's connection check inspect package/protocol readiness without a license checkout. `licenseStatus: not_checked` means no checkout was attempted, not that the license is broken.

For the current hosted Studio, follow [VM_HOSTING.md](../VM_HOSTING.md). `deploy-studio.py` requires both frontend builds and refuses to replace a listening application. Restart only after checking active and uncertain jobs; a stopped frontend does not necessarily cancel a solver process. Saved data persists, but in-memory conversations do not survive restart.

## Optional Fluent integrations

- [Official API discovery](../FLUENT_MCP.md): configure `FLUENT_MCP_PYTHON`; optional `FLUENT_MCP_API_OBJECTS_PATH` selects the worker's catalog.
- [Native graphics](../integrations/fluent_post/README.md): configure the separate post interpreter and bundled adapter. Core execution and extracted-data plots remain usable without this optional private dependency.

All private configuration belongs in ignored files. Keep custom data/output folders ignored or outside the repository. Neither demo logins nor provider API keys belong in GitHub or generated-code archives.
