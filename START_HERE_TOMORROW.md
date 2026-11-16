# Historical handoff

This file records the original November 5 handoff. For the current version, use
the [prototype package](PROTOTYPE_PACKAGE.md) and [demo walkthrough](docs/DEMO.md).

# Resume the simulation demo

Branch: `feat/simulation-studio-demo`

## Open the app

Connect Tailscale and open the **[hosted demo](http://100.88.230.43:7860/)**.
Sign in with the existing OpenCode credentials. The app runs on the Windows
machine, so the Mac's local server can be closed. Windows must stay awake with
Tailscale and OpenCode running; Studio starts when its Windows user signs in.
See [VM_HOSTING.md](./VM_HOSTING.md) for hosting and restart details.

For local development instead:
On the configured Mac, open **Start Mac App.command** if the local server has
stopped, then visit <http://127.0.0.1:7860/>. Keep Tailscale connected when you
want to use the OpenCode chatbot or remote Ansys worker.

On a fresh checkout, follow [MAC_REMOTE_SETUP.md](./MAC_REMOTE_SETUP.md).
Private connection settings and credentials remain local and are excluded from
Git. Frontend build outputs are also excluded; the setup script builds them.

## Use the new demo

Import [`examples/simple-bracket/simple-bracket.step`](./examples/simple-bracket/simple-bracket.step),
or choose **simple-bracket.step** from the left folder panel. It is already saved
on the hosted demo. The new original model has nine faces and no holes.

- **Support:** the broad outside back of the upright at **X = 0 mm**.
- **Load:** the small flat tip of the horizontal arm at **X = 80 mm**.
- **Demo assumptions:** Structural Steel, linear static/small deformation, one
  fully fixed back face, and a total **100 N in global −Z** on the tip.

Start with this prompt:

> Help me set up this simple bracket. First identify and highlight the broad,
> flat outside back face at X = 0 mm. Explain why you chose it and wait for my
> confirmation before applying a fixed support.

Continue with the [step-by-step prompts](./examples/simple-bracket/README.md).
After the support, load and assumptions are reviewed, ask the agent to generate
a coarse/medium/fine mesh comparison and show its Python before running it.

The composer now also offers **Autonomous simulation** to proceed without
per-step confirmation, and a separate **Visual assistance** switch. Visual
assistance lets the model see CAD screenshots, request other angles, and map a
pixel to an exact face. It can look without clicking. Both are optional; Guided
simulation with visual assistance off retains the original workflow.

## Saved state and current limits

The branch contains the React frontend, shared viewer/chat/MCP state, confirmation
workflow, generated-Python execution path, remote worker integration, tests, and
the new STEP demo plus generator. The original complex bracket's saved support
annotations are still in this Mac's local workspace.

CAD files and saved conditions persist on the machine hosting the app; the Mac
and Windows workspaces are separate. Chat history and pending
confirmations live in the running process, so reopening after a server restart
starts a fresh conversation. Use the prompts above to reconstruct the demo.

The simpler bracket has been geometry-checked and solved in the real remote Ansys
worker using the [autonomous demo prompts](./examples/simple-bracket/AUTONOMOUS_DEMO.md).
A 5 mm quadratic-mesh baseline completed with 2,024 nodes and 318 elements; its
maximum deformation was 0.0502465 mm and equivalent stress 23.4997 MPa.
Automated UI test solver outputs are still synthetic. The agent previously hit
its per-turn step limit while working with the complex bracket; the new geometry
makes face identification simpler, but the general step-limit behavior has not
been changed or claimed fixed.
