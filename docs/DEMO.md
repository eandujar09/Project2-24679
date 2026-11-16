# Demo walkthrough

Use [simple-bracket.step](../examples/simple-bracket/simple-bracket.step): one solid, nine faces, 80 × 30 × 60 mm overall, 8 mm thickness and a 6 mm inside bend radius. This STEP contains geometry only.

## Guided Mechanical demo

Import the file, choose **Mechanical**, and leave **Guided simulation** selected. Visual assistance is optional. Start with:

> This is a steel shelf bracket. Its broad outside back is attached to a rigid wall, and its free tip carries a total downward force of 100 N. Help me set up a linear static, small-deformation demo using Structural Steel. Identify and highlight the support and load faces, preview their graphics, and ask me to confirm before applying anything. Do not add gravity or extra loads. Ask if my description is ambiguous.

The agent should propose the broad outside back of the upright as the fixed face, and the small flat end of the arm as the loaded face. Check this visually. The supplied model's back is at **X = 0 mm**, area **1,800 mm²**; its tip is at **X = 80 mm**, area **240 mm²**. Downward for this demo means **global −Z**, not downward on the screen. Face numbers are importer-specific; use geometry or a click when correcting a choice.

If necessary, clarify:

> By downward I mean global negative Z: Fx = 0 N, Fy = 0 N, Fz = −100 N. Use the single flat tip face. The combined force must remain 100 N.

Confirm each intended proposal in chat. Violet is the agent's highlight; amber is your selection. Proposed symbols appear before confirmation; confirming applies the saved condition. Clicking a face alone does not apply a support or approve a proposal.

Then request:

> Review the saved setup and write PyMechanical code for one baseline static analysis with a 5 mm quadratic mesh. Reuse the confirmed support and force through the exact face keys. Report actual mesh counts, maximum displacement in mm and maximum equivalent stress in MPa, and export both contour plots. Show me the code before running it.

Review and confirm the code. Expected outputs are generated Python, actual worker status/logs, measured values, plots and downloadable artifacts. A successful solve has a verified solve record; inspection-only code can finish successfully without solving.

For a mesh comparison:

> Compare 8, 5 and 3 mm meshes using the same material, support and total load. Do not add loads again inside the loop. Stay within the resource limits. Report mesh counts, displacement, stress and percentage changes. For this demo, compare the last two displacement maxima against a 5% criterion; discuss stress sensitivity separately. Show the code for confirmation.

The [reference results](../examples/simple-bracket/verified-demo.json) are historical checks, not guaranteed outputs from every new generated program. More explicit [tested prompts](../examples/simple-bracket/AUTONOMOUS_DEMO.md) are retained for troubleshooting.

## Thermal and fluid demonstrations

Choose **Heat transfer** to discuss temperature, heat flux, convection, radiation or insulation. Supply physical units, material properties and steady/transient intent. Thermal graphics and saved annotations are implemented; the package does not claim a separately verified thermal solve.

Choose **Fluid dynamics** to identify whether CAD is already the fluid volume, a solid obstacle, or reference geometry. A confirmed box/cylinder definition can construct a separate fluid STEP with checked subtraction. Custom internal-passage extraction is not implemented. Supply fluid properties, boundaries, regime and numerical criteria before requesting code. See [domain preparation](../HEAT_TRANSFER_AND_DOMAINS.md), [Fluent scope](../fluent/README.md) and the [authored water example](../examples/fluent-native-steady-water.py). Reference water/laminar/numerical choices must not become hidden defaults for a different problem.

## Exports

| Export | Meaning |
| --- | --- |
| Mechanical setup `.mechdat` | Native setup/database. Building a setup before solving does not create results; after execution the available native database reflects that job. |
| Solved simulation `.mechpz` | Native Mechanical archive including solver results, available only for a verified matching solved result. |
| Simulation ZIP | Input snapshot, source, logs, measured results and native job artifacts. Fluent case/data are here. |
| Annotation JSON | Portable saved face/setup annotations; not a native solver project. |

Mechanical exports are disabled until sufficient applicable setup or a matching solved result exists. Unconfirmed proposals are excluded. Fluent-native files do not become Mechanical exports. Unsupported thermal/preset reconstruction is rejected instead of silently treated as structural loading.

## Starting again and failures

- Fresh **Import CAD** creates an empty setup. **Saved Models** restores conditions. **New conversation** preserves the saved setup; it does not reset supports or loads.
- If a face is wrong, select the intended face and correct the message. Recheck the revised preview before approval.
- If the model reaches its turn limit, continue the conversation; saved state remains. A step-limit message is not a solved result.
- If code fails, inspect the real error and revised code. Guided mode requires fresh execution approval.
- If transport is uncertain, recover the existing job. Do not repeatedly request a new solve just because a response was lost.
- If native graphics fail after convergence, retain the valid flow result and handle postprocessing separately; do not rerun the flow for a picture.

The live app depends on VPN reachability, the Windows host, OpenCode/model availability and solver access. [Setup](SETUP.md) and [limits](LIMITATIONS.md) describe these dependencies.
