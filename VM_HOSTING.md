# Windows demo hosting

The demo is available at **http://100.88.230.43:7860/** on the existing Windows
OpenCode/Ansys machine. Connect to Tailscale and sign in with the existing
OpenCode username and password. This is a private VPN address, not a public
website. The Mac does not have to keep its local app running.

The Windows machine must stay awake with Tailscale and OpenCode running. Studio
starts when the `neoth` Windows user signs in, using a shortcut in that user's
Startup folder. It is not a system service and does not start before sign-in.
Closing a browser tab does not stop it.

## Use the demo

Open the folder panel on the left and choose **simple-bracket.step**. It is
already saved on the Windows host. The [guided prompts](examples/simple-bracket/README.md)
walk through the back support, tip load, assumptions, and mesh study.

The Windows workspace is separate from the Mac's workspace. Uploaded CAD and
confirmed setup annotations persist on Windows; conversations and unconfirmed
proposals are held in memory and reset when the app restarts. This is a shared
demo workspace with one login, not isolated accounts for multiple customers.

## Files and process

- App: `%LOCALAPPDATA%\Project2Studio`
- Dedicated Python: `.venv\Scripts\python.exe` inside that directory
- Private settings: `.env.local.json`, `.env.opencode.json`, `.env.host.json`
- CAD and saved setup: `gradio-data`
- Log: `studio-runtime\server.log`
- Current launch record: `.env.host-state.json`
- Startup shortcut: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Project2 Simulation Studio.lnk`

The existing Ansys worker and its Python environment are unchanged. Studio uses
the same authenticated OpenCode API for chatbot calls and Ansys jobs. Credentials
remain in ignored configuration files and were not committed to GitHub.

To restart Studio from PowerShell on the Windows host, first check the recorded
PID belongs to this app, then stop that process and launch the startup shortcut:

```powershell
$studioRoot = Join-Path $env:LOCALAPPDATA 'Project2Studio'
$studioState = Get-Content (Join-Path $studioRoot '.env.host-state.json') | ConvertFrom-Json
$studioProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($studioState.pid)"
if ($studioProcess -and $studioProcess.CommandLine.Contains((Join-Path $studioRoot 'scripts\run_vm.py'))) {
    taskkill /PID $studioState.pid /T /F
}
Start-Process (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\Project2 Simulation Studio.lnk')
```

Only restart while no chat turn or Ansys job is running. A stopped frontend does
not necessarily cancel a submitted remote solver job.

## Deploy an update

On the configured Mac checkout, build both frontends, commit or stage intended
source changes, stop the running Studio process on Windows, then run:

```sh
npm run build:gradio
npm run build:studio
.venv-gradio/bin/python scripts/deploy-studio.py
```

The deployment script uses the existing OpenCode file and shell APIs; SSH is not
required. It packages Git-tracked source and built frontends, transfers private
connection configuration only to this same Windows host, and preserves the
hosted CAD data. It refuses to replace an app that is still listening on its port.
It installs the current user's startup shortcut and launches Studio independently
of the Mac's terminal connection.

For a new Windows installation, first create the dedicated Python 3.12 environment
at `%LOCALAPPDATA%\Project2Studio\.venv` and install `requirements-gradio.txt` into
it. The current host already has this environment. Future requirements changes
must also be installed there before deploying.

## Verified for this deployment

- Authenticated browser access from the Mac over Tailscale.
- Simple STEP import and rendering: one solid, nine faces.
- A real OpenCode chat response identifying the 80 × 30 × 60 mm model.
- Remote worker connection and installed PyMechanical availability.
- Login enforcement for the UI, API, MCP and result-file routes.
- Startup shortcut launch and persistence after the invoking remote shell exits.
- 68 Python tests and both Studio browser tests, including HTTP-compatible chat IDs.

The [autonomous bracket demo](examples/simple-bracket/AUTONOMOUS_DEMO.md) was
also tested against the real remote worker: its 5 mm quadratic-mesh baseline
completed a verified solve and exported deformation/stress plots. This validates
that tested case; arbitrary generated analyses can still fail or need clarification.
