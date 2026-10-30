# Deterministic annotated-STEP → Mechanical simulation

`run.py` is a fixed, non-agentic script. It does not generate Python/APDL from
prompts. It consumes a validated JSON request, creates a new Mechanical database,
imports the exact STEP bytes, resolves CAD faces geometrically, applies conditions,
meshes, solves, and exports numerical results and contour images.

## Gradio workflow

1. Open a **single-solid** STEP model in the Gradio app.
2. Annotate a fixed support or prescribed displacement, plus a nonzero load or
   displacement. Save annotations before running. A load cannot share a face
   with a support in this conservative first iteration.
3. Expand **Ansys Mechanical · deterministic static structural simulation**.
4. Supply the Python interpreter from **your PyMechanical environment** in
   **Mechanical Python executable**, or set `MECHANICAL_PYTHON` before starting
   Gradio. This environment is an explicit user input; no personal directory is
   auto-detected. Install `requirements-mechanical.txt` in that environment if
   needed. Check mesh element size and modeling assumptions.
5. Confirm the assumptions and choose **Run simulation in Mechanical**.
6. Review the report and total-deformation/von-Mises-stress contours. Download
   the ZIP for the Mechanical project (`model.mechdb` and its associated files),
   text results, original STEP, mapping evidence, settings, input request, and log.

Each click creates a new directory under
`gradio-data/exports/simulations/<timestamp>-<unique-id>/`. No existing Mechanical
session is attached to or modified. A separate interpreter isolates .NET from
Gradio and closes Mechanical after each run. Runs time out after 15 minutes;
only that worker's process tree is terminated. Failed runs retain logs/reports
and do not display contours from an older successful run. Results identify their
model hash and snapshot; changing annotations does not automatically rerun.

## CLI (same worker, no Gradio UI required)

First export annotation JSON from the Python workspace and retain its exact STEP.
Prepare in the environment with OpenCascade:

```powershell
.\.venv-gradio\Scripts\python.exe -m mechanical.prepare --step "model.step" --annotations "annotations.json" --output "request.json" --element-size-mm 3
```

Then run in your PyMechanical environment (the example creates a local one;
an existing compatible environment can also be used):

```powershell
python -m venv .venv-mechanical
.\.venv-mechanical\Scripts\python.exe -m pip install -r requirements-mechanical.txt
$env:MECHANICAL_PYTHON = (Resolve-Path .\.venv-mechanical\Scripts\python.exe).Path
& $env:MECHANICAL_PYTHON -m mechanical.run --request "request.json" --output-dir "simulation-results"
```

Run both commands from this repository's root. The output directory **must not
exist**. The CLI writes `report.json`, `totalDeformation.png`,
`vonMisesStress.png`, result `.txt` files, and the Mechanical project. The images
can be opened directly; Gradio displays these same files. Exit code 0 means
successful solve and exports; exit code 1 means failure. To set up another
Mechanical interpreter, install `requirements-mechanical.txt` there and ensure
Mechanical 261 and a usable license are installed.

## Explicit analysis contract

- Mechanical **261 / 2026 R1**, tested with PyMechanical **0.12.7**.
- Exactly **one solid**, linear static structural, small deformation, one load
  step ending at 1 s. This is not transient analysis. No contacts, shells,
  beams, thermal fields, plasticity, or inertia.
- Mechanical 261's **Structural Steel** engineering-data library material is
  assigned explicitly. No material is inferred from STEP or comments. The
  actual Mechanical project is retained for auditing its material definition.
- Quadratic, patch-conforming tetrahedral mesh with explicit global element size.
  The worker refuses meshes exceeding **32,000 nodes or elements**, a conservative
  application limit independent of the license's actual limit.
- Direct solver, **one CPU core**, distributed solving/GPU disabled,
  **weak springs off**. Underconstrained models must fail; no stabilizing
  constraints or springs are invented. A support's presence does not guarantee
  all rigid-body modes are constrained.
- Fixed support constrains all solid-face translations. Displacements prescribe
  all global X/Y/Z components in **mm**, including zeros. Forces are total face
  vectors in global **N**, not nodal forces or tractions. Pressure is **MPa**,
  positive inward and negative outward.
- Multiple forces on a face are summed componentwise in stable ID order;
  pressures are summed algebraically. Original IDs and the combined conditions
  are recorded. Multiple supports or loads on a constrained face are rejected.
- Comments are retained as provenance, **not interpreted as solver commands**.

## Face identity and fail-closed mapping

The request records the original file's SHA-256. Both preparation and the worker
verify it. Python's `python-ocp-v1` face keys are never treated as Mechanical IDs.
The source importer obtains exact area, centroid, trim vertices, nine curve
samples per boundary edge, and at least three interior parametric surface
samples with outward normals for every face. Artificial periodic seams are
excluded from trim-edge lists because they are not physical boundaries.
Interior sampling first tries a coarse UV grid, then uses the actual trimmed
face's UV triangulation for deterministic barycentric seeds, followed by a bounded
adaptive UV search if needed. Every point must classify strictly inside the
original B-rep, have a well-defined unit normal, and be distinct. Seeds are
evaluated on the exact surface, not on 3D triangle chords. This handles thin,
diagonal, holed, and heavily trimmed faces without accepting boundary/outside
points or lowering the minimum of three verified interior samples.

Mechanical must have the same face count. Each source face must match exactly
one Mechanical face, using:

- Coarse relative area error ≤ **0.02** and centroid distance ≤ **0.1 mm**.
  Mechanical's API reports faceted mass properties; these are **only candidate
  filters**, not acceptance criteria. If area exceeds that coarse limit, acceptance
  requires the bidirectional boundary-coverage test below. Small trimmed faces can
  have substantially inaccurate faceted areas. Import requests VeryFine faceting.
- Normally the same trim-vertex/edge counts, bidirectional vertex distances ≤ **0.0001 mm**,
  and a unique one-to-one boundary-edge match. Every sampled curve point must
  match the candidate's exact edge within **0.0001 mm**, with projection clamped
  to that edge's actual parameter range (closed periodic edges wrap).
- If edge/vertex counts differ, redundant boundary subdivisions may be accepted
  **only with bidirectional coverage**: source curve polyline nodes, segment
  midpoints, original curve samples, and vertices project to exact Mechanical
  trim edges; 65 exact samples per Mechanical edge and its vertices must also
  lie within the source boundary union. Source polylines use **0.000001 mm**
  requested deflection, reserved from the **0.0001 mm** reverse-check budget.
  This tests boundary geometry rather than demanding identical edge segmentation.
  It remains finite sampling, not a proof for arbitrary curves. The report records
  forward/reverse errors and which faces used this path.
- Projected interior surface-point distance ≤ **0.0001 mm**.
- Outward unit-normal dot product ≥ **0.999**, at every sample.
- A one-to-one mapping across **all** source faces, not just loaded faces.

No nearest-face, numeric-ID, name, or traversal-order fallback is used. Face splits,
face merges, coincident faces, missing trim signatures, insufficient UV samples, mismatched units, or ambiguous
matches stop the run. This intentionally rejects some otherwise valid geometry;
extend and validate the matcher rather than loosening tolerances blindly.
Old prepared requests without trim signatures must be regenerated; existing
workspace annotations/face keys do not need to be changed. `--map-only` on the
worker validates geometry without meshing or solving. Mapping failures write
`mapping-diagnostics.json` with candidate rejection reasons and measured errors.

Finite sampling is a conservative correspondence test, not a mathematical proof
of identical topology for arbitrary surfaces.

## Results and verification

The report records min/max total deformation (**mm**), equivalent von Mises stress
(**MPa**), mesh counts, Mechanical messages/status, mapping errors, normalized
conditions, settings, software versions, and the request SHA-256. The exported
project and text fields allow independent inspection. Peak stress can be
mesh-dependent/singular; this script does not perform mesh-convergence, failure,
fatigue, buckling, or design-approval checks. Repeatable setup is not a guarantee
of bit-identical numerical output or physical validity.

Unlicensed unit tests:

```powershell
.\.venv-gradio\Scripts\python.exe -m unittest discover -s tests/python -v
```

Optional actual Mechanical regression solves (synthetic cylinder only):

```powershell
$env:MECHANICAL_TEST_PYTHON = $env:MECHANICAL_PYTHON
.\.venv-gradio\Scripts\python.exe -m unittest discover -s tests/mechanical -v
npm.cmd run test:gradio
```

The live test covers fixed support plus force, pressure, or displacement; checks
saved images/archive; and compares displacement against the axial elastic
cylinder estimate (6% tolerance for the finite mesh/end constraints).
With that same environment variable, Playwright also performs a real solve from
Gradio and verifies both displayed contours and the downloadable archive.
