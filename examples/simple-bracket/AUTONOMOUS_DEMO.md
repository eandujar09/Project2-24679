# Repeatable bracket demo

Import [simple-bracket.step](./simple-bracket.step). It is one solid with nine faces:
80 × 30 × 60 mm overall, 8 mm thickness, and a 6 mm inside bend radius.

In the chat composer, choose **Autonomous simulation** and turn **Visual assistance**
on. Keep the browser tab open so it can supply screenshots. Send one prompt at a
time and wait for the assistant to finish before sending the next. These prompts
fully specify a demonstration load case; the agent still chooses its actions and
writes its own analysis code.

The selected face shown in amber belongs to you. Violet highlights show what the
agent picked. Image-pixel picks do not alter your selection.

## 1. See and pick a face (no simulation)

> Use the screenshot to identify the broad top surface of the horizontal arm. Pick one pixel inside it with pick_viewport_face and report the returned face number. Only identify and highlight it; do not change the simulation setup or run code.

## 2. Save the support and load

> Set up this demonstration bracket using Structural Steel and a linear static, small-deformation analysis. Fully fix the single broad outside back face at global X = 0 mm (area 1800 mm²). Apply a total force of 100 N to the single flat tip face at global X = 80 mm (area 240 mm²), with global components Fx = 0 N, Fy = 0 N, Fz = -100 N. Use an initial 5 mm mesh setting. Identify the faces from their geometry, highlight your choices and save the setup. If these conditions already exist, reuse or update them instead of adding duplicates. Report the final support and load. Do not run a simulation yet.

## 3. Run one baseline analysis

> Run one baseline analysis for the saved bracket setup using your own PyMechanical code. Assign Structural Steel, use linear static small deformation and a 5 mm quadratic mesh. Use the exact saved face keys through ctx.selection for the fixed support and the total 100 N force in global negative Z. Do not add gravity or extra loads. Use ctx.generate_mesh and ctx.solve, then report actual nodes, elements, maximum total deformation in mm and maximum equivalent stress in MPa. Export both result plots with ctx.capture and save the project. If an API call fails, use its actual error to revise the code. Do not claim a solved analysis unless a verified solve completed.

## 4. Optional mesh comparison

> Using the same saved support, load and material, write and run a mesh comparison at 8, 5 and 3 mm. Reuse the same loads while remeshing; do not add them again inside the loop. Stay within the worker's 32000-node/element limits. Record actual nodes, elements, maximum total deformation and maximum equivalent stress for each successful solve. Calculate percentage changes between successive meshes. Use less than 5% change in maximum total deformation as this demo's comparison criterion, and state whether the final pair meets it. Report stress changes separately and explain any sensitivity near fixed edges. Export deformation and stress plots from the finest successful mesh. Report incomplete runs honestly.

## Starting again

Open the saved **simple-bracket.step** model and start a new conversation. A new
conversation keeps saved supports and loads, so prompt 2 explicitly reuses or
updates them. Choose the two composer settings again if the app was restarted.
Use the same unmodified STEP file for this sequence.

If the agent stops to ask an essential question, answer it before continuing.
If a run is still active or its connection is uncertain, ask it to recover the
existing run; do not repeatedly submit a new solve. The same completed program
may return its saved results rather than launching a duplicate.

The support is the outside back at X = 0 mm, area 1800 mm²; the load goes on the
flat tip at X = 80 mm, area 240 mm². The prompts use those geometric descriptions
instead of relying on face numbering.

## Tested result — November 5, 2026

This sequence was exercised with the configured OpenCode model and real Mechanical
261 worker. Screenshot picking identified the broad top as Face 3, and setup
identified Face 7 for the fixed back and Face 2 for the loaded tip. Repeating the
setup prompt retained exactly one support and one force. The baseline and all
three mesh-study solves completed successfully.

| Mesh size | Nodes | Elements | Max deformation (mm) | Max equivalent stress (MPa) |
| --- | ---: | ---: | ---: | ---: |
| 8 mm | 655 | 80 | 0.0502165 | 20.0510 |
| 5 mm | 2024 | 318 | 0.0502465 | 23.4997 |
| 3 mm | 7276 | 1330 | 0.0503228 | 23.4936 |

The 5→3 mm maximum-deformation change was **0.152%**, meeting this demo's 5%
comparison criterion. This measures the tested global response; it does not
establish convergence at every local stress concentration. AI-generated code
can vary between runs, so use these as reference results rather than a promise
of identical output. The 5 mm result was identical in the baseline and study.
