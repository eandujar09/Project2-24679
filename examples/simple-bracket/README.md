# Simple bracket demo

Import [`simple-bracket.step`](./simple-bracket.step) into Simulation Studio.
This original model has one solid and nine CAD faces, with no holes or split
hole walls. It is intended to make the selection-and-confirmation workflow easy
to demonstrate. It contains geometry only; the agent still chooses its tools and
writes its own PyMechanical code in response to the conversation.

Dimensions are in millimeters: 80 mm reach along X, 30 mm width along Y,
60 mm height along Z, and 8 mm wall thickness. The inside bend has a 6 mm radius.

## Two faces to discuss

| Role in this demo | Surface | Extents in mm | Area |
| --- | --- | --- | --- |
| Fixed mounting face | Broad, flat outside back of the upright | X = 0; Y = 0–30; Z = 0–60 | 1,800 mm² |
| Loaded tip | Small, flat rectangular end of the horizontal arm | X = 80; Y = 0–30; Z = 0–8 | 240 mm² |

Each is one complete CAD face. Ask the assistant to highlight them using their
position and geometry; face numbers are assigned by the importer and should not
be assumed across regenerated files. Use the Model panel to inspect a face, and
orbit the part to view the outside mounting surface. The rounded bend makes the
inside corner smooth, but constraint/load edges can still produce local stress
peaks. This is a demonstration setup, not a validated physical mounting design.

## Suggested conversation

Send one prompt at a time and review each confirmation before proceeding.

1. **Locate the support:** “This is a demo shelf bracket attached to a rigid wall.
   Identify the broad, flat outside back of the upright at X = 0 mm. Highlight it
   and explain your interpretation. Do not apply a support yet.”
2. **Fix that face:** “Use that single back face as a fully fixed support for this
   demo. Explain the constrained directions and ask me to confirm.”
3. **Locate the load:** “Highlight the small, flat end face of the horizontal arm
   at X = 80 mm. Propose a total force of 100 N in global negative Z on that face.
   Explain the direction and wait for confirmation.”
4. **Review:** “Assume Structural Steel and a linear static, small-deformation
   analysis for this demo. Review the complete setup and ask about any missing
   information. Verify there is exactly one fixed face and one 100 N force.”
5. **Generate the study:** “Write PyMechanical code comparing coarse, medium, and
   fine meshes. Propose suitable sizes within the installed license limits. Show
   the code and wait for confirmation before running it. Compare node/element
   counts, displacement, and stress, and explain whether those quantities are
   converging. Distinguish local stress peaks from the overall response.”

The support and force are conversational demo assumptions. The application does
not load preset conditions or automatically execute an analysis for this file.

## Recreate the geometry

From the repository root, after installing the Mac dependencies:

```sh
.venv-gradio/bin/python scripts/make_demo_bracket.py
```

The generator constructs an extruded L profile with an inside circular fillet
using OpenCascade and checks the solid before exporting STEP.
