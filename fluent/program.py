"""Agent-authored Fluent runtime, parallel to mechanical.program.PROGRAM_GUIDE."""
PROGRAM_GUIDE = '''FLUENT WORKFLOW (run_fluent_code): execute YOUR PyFluent Python in a fresh
Fluent 261 worker on the exact uploaded fluid-volume CAD. Like run_mechanical_code,
this is not a setup-template renderer. YOU author sizing, surface mesh, region
handling, volume controls, physics, materials, boundary conditions, initialization,
numerical settings, results, loops and calculations. The old ctx.mesh() and
ctx.configure() template calls are REMOVED and rejected; never submit them.

The worker imports face-partitioned STL as Mesh in mm into a fresh Watertight
Geometry workflow, but does not generate a mesh or assign any physics/material/BC.
For curved CAD, prefer explicitly reinitializing the same workflow and importing
ctx.artifact('source.step') as CAD File in mm, with CadImportOptions OneZonePer='face',
OneObjectPer='Body', ImportCurvatureDataFromCAD=True in BOTH Import Geometry AND
Generate the Surface Mesh. Rebind tasks=workflow.TaskObject AND ctx.tasks=tasks.
This preserves analytic geometry and face partitions that STL remeshing may damage.
review_fluent_workflow returns the proven authored reference, not an injected preset.
Choose curvature resolution/volume fill/stabilization in your code for this job;
the known saved-water settings are not guarantees for other CAD or physics.
Globals: ctx, meshing (the live PyFluent meshing session), workflow and tasks.
Do not launch or import ansys, create another session, use private APIs, TUI/Scheme,
arbitrary file/network I/O or nested execution. Computation-helper imports match
Mechanical: math/statistics/json/collections/itertools.

ctx.geometry: actual source CAD face descriptors, CAD volume, imported surface path,
units and mapping status. ctx.analysis: saved OPTIONAL user-approved laminar-flow
assumptions, NOT a default or preconfigured analysis. ctx.conditions: saved optional
SI face conditions. ctx.selected_face: original selected CAD face key or None.
Saved assumptions and conditions are binding: implement them in YOUR setup code;
do not silently replace them. If absent, establish intended physics and values
with the user in the exact code proposal. No implicit water, laminar model or walls.

ctx.describe(obj): inspect public API members. Use the corresponding Fluent MCP
server for discovery/validation. Studio exposes find_fluent_api/get_fluent_api_help,
validate_fluent_api_code for underlying solver/session snippets, check_fluent_worker,
and separate local validate_fluent_program for full ctx code. Its offline catalog
can differ from Fluent 261. Inspection-only code can complete with zero verified
solves; that is NOT a successful simulation.

Mesh preparation is agent-authored. Inspect tasks and their live arguments. Set
explicit surface controls, execute the surface task and describe geometry. If using
ctx.update_regions(), first describe all enclosed regions as fluid, then execute
Update Boundaries. ctx.update_regions() identifies the unique CAD-volume match
and marks non-fluid interiors dead using old AND new region-type lists. It sets
no sizing, fill method, material or solver physics. Ambiguity fails before meshing.
Never identify regions by largest size or face-derived labels. Alternatively author
verified region handling yourself. Preserve the obstacle void and every source face.

Set tasks['Generate the Volume Mesh'].Arguments with explicit VolumeFill and chosen
controls, then solver = ctx.generate_mesh(). This executes that configured task,
switches to solver, enforces one fluid/no solid zone and 32000 cells, and verifies
one-to-one trimmed-CAD face correspondence. No fill method is supplied by the worker.
Optional tolerance_mm is positive and <=0.1 mm; never loosen checks to hide bad CAD.
Do not call switch_to_solver directly. Split/merged/ambiguous faces fail, never guess.
ctx.solver: the checked public PyFluent solver. ctx.selection([face_key,...]) returns
the exact verified zone names, analogous to Mechanical's ctx.selection.

Author the solver models/materials/conditions/numerics through solver.settings.
For saved face conditions, use ctx.selection and explicit set_zone_type plus actual
per-type settings. Inlet components are global m/s, outlet gauge pressure is Pa,
geometry mm, density kg/m^3, dynamic viscosity Pa s, operating pressure absolute Pa.
Saved wall {} means stationary no-slip; symmetry {} means symmetry. UI annotations
are not automatically applied. Select and execute the agreed initialization method.

ctx.solve(max_iterations=..., residual_tolerance=..., mass_imbalance_tolerance=...,
          mass_flow_zones=ctx.selection([...])):
resource-checked steady iteration, actual ACTIVE residual-equation checks and
measured open-boundary mass balance. Specify all open boundaries, not a subset.
Arguments can be omitted only when supplied by saved approved ctx.analysis/conditions.
There is no fixed laminar equation list or hidden initialization. Always use ctx.solve
instead of direct iterate/calculate. Maximum 2000 TOTAL requested iterations per job;
multiple checked solves are allowed. Nonconvergence fails; native case/data and
diagnostics are retained. The helper currently supports steady flow in one fluid
cell zone, not transient stepping, CHT/multiple regions or automatic FSI. Do not
promise unimplemented scopes or select Mechanical for fluid physics.

ctx.record(name,value,unit=None), ctx.table(name,rows): real measured/calculated
findings, CSV/JSON. ctx.capture(field,name): actual pressure or velocity-magnitude
boundary-surface PNG/CSV rendered with Matplotlib (not native Fluent screenshots
or volume slices). Studio can enrich converged results through the separate
post-only MCP renderer, or use render_fluent_results without rerunning the solve.
Other quantities may be read through
the public solver APIs and recorded; never fabricate results. ctx.save_case(): saves
case.cas.h5 and, after actual iterations, case.dat.h5 inside this job. ctx.artifact(name)
returns a job-local export path. Native files are also saved by the harness.

Execution uses the SAME confirmation, fingerprint deduplication, three-attempt
limit, worker transport, time-limited process, recovery and results flow as Mechanical.
recover_fluent_run retrieves an uncertain existing job; never resubmit it. Correct
YOUR script when it owns the error; report worker import/mapping defects rather
than bypassing them. No solve occurs merely because Python finishes. Read verifiedSolves.
One CPU, 32000 cells, 15-minute job deadline. Source checks are misuse guards, not
an OS security sandbox. No automatic two-way FSI or license assumptions.
'''
