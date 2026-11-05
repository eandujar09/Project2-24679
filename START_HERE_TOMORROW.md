# Resume the simulation demo

Branch: `feat/simulation-studio-demo`

## Open the app

On the configured Mac, open **Start Mac App.command** if the local server has
stopped, then visit <http://127.0.0.1:7860/>. Keep Tailscale connected when you
want to use the OpenCode chatbot or remote Ansys worker.

On a fresh checkout, follow [MAC_REMOTE_SETUP.md](./MAC_REMOTE_SETUP.md).
Private connection settings and credentials remain local and are excluded from
Git. Frontend build outputs are also excluded; the setup script builds them.

## Use the new demo

Import [`examples/simple-bracket/simple-bracket.step`](./examples/simple-bracket/simple-bracket.step),
or choose **simple-bracket.step** from the left folder panel if it is already
saved on this Mac. The new original model has nine faces and no holes.

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

## Saved state and current limits

The branch contains the React frontend, shared viewer/chat/MCP state, confirmation
workflow, generated-Python execution path, remote worker integration, tests, and
the new STEP demo plus generator. The original complex bracket's saved support
annotations are still in this Mac's local workspace.

CAD files and saved conditions persist locally. Chat history and pending
confirmations live in the running process, so reopening after a server restart
starts a fresh conversation. Use the prompts above to reconstruct the demo.

The simpler bracket has been geometry-checked; no real Ansys solve has yet been
run for it. Automated UI solver outputs are synthetic. The agent previously hit
its per-turn step limit while working with the complex bracket; the new geometry
makes face identification simpler, but the general step-limit behavior has not
been changed or claimed fixed.
