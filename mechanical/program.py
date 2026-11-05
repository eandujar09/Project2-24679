"""Contract for model-authored Python, separate from the legacy fixed analysis."""
import ast
import hashlib

MAX_CODE_BYTES = 64000


def validate_program(program):
    if not isinstance(program, dict):
        raise ValueError('A generated program is required.')
    code = program.get('code')
    if not isinstance(code, str) or not code.strip() or len(code.encode()) > MAX_CODE_BYTES:
        raise ValueError('Supply nonempty Python code of at most 64 KB.')
    for key in ('title', 'objective'):
        if not isinstance(program.get(key), str) or not program[key].strip():
            raise ValueError('The generated program needs a title and objective.')
    try:
        tree = ast.parse(code, filename='agent.py')
        compile(tree, 'agent.py', 'exec')
    except (SyntaxError, ValueError) as exc:
        raise ValueError('Generated Python does not compile: ' + str(exc)) from exc
    # These are accidental-misuse checks, NOT an OS or Python security sandbox.
    # Mechanical's object model is broad; this runs with the worker account's permissions.
    allowed_imports = {'math', 'statistics', 'json', 'collections', 'itertools'}
    forbidden_calls = {'exec', 'eval', 'compile', '__import__', 'open', 'input', 'breakpoint', 'exit', 'quit'}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or '']
            if any(m.split('.')[0] not in allowed_imports for m in modules):
                raise ValueError('The worker already supplies Mechanical globals. Imports are limited to computation helpers; no system/network modules.')
        if isinstance(node, ast.Name) and node.id.startswith('__'):
            raise ValueError('Private Python runtime access is not allowed in analysis code.')
        if isinstance(node, ast.Attribute) and node.attr.startswith('_'):
            raise ValueError('Use public Mechanical APIs rather than private runtime attributes.')
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in forbidden_calls:
            raise ValueError('Use ctx artifact helpers; arbitrary file I/O and nested code execution are not analysis actions.')
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {'Solve', 'SendCommand', 'ExecuteCommand', 'ExecuteScript', 'ExecuteScriptFromFile'}:
            raise ValueError('Use ctx.solve(analysis) for resource-checked solving; nested scripts/commands are not allowed.')
    digest = hashlib.sha256(code.encode()).hexdigest()
    if program.get('sha256', digest) != digest:
        raise ValueError('Generated code hash mismatch.')
    return digest


PROGRAM_GUIDE = '''The tool run_mechanical_code executes YOUR Python script in a fresh Mechanical 261
PyMechanical 0.12.7 embedded App on the remote machine, with the exact uploaded STEP already imported.
It is not a template renderer. You author the analysis, material assignment, mesh controls, boundary
conditions, result objects, loops, calculations and refinement criteria. No analysis is pre-created.
Globals: Model, ExtAPI, DataModel, Tree, Graphics, Quantity, all Mechanical enums, Ansys, and ctx.
Do not create another App or import ansys; the worker supplied these. Standard math/statistics/json/
collections/itertools imports are allowed. Do not access system/network modules, run shell commands,
read personal files, use private Python attributes, or execute nested scripts. This is an analysis worker.

ctx API (available in every script):
- ctx.geometry: actual imported body descriptors, faces and named selections, plus face-mapping status.
- ctx.bodies: actual Mechanical Body objects. Material assignment is YOUR code, e.g. body.Material = 'Structural Steel'.
- ctx.face_ids: original CAD face key -> verified Mechanical face ID. ctx.selection([face_key, ...])
  returns a Mechanical geometry selection. This raises if exact mapping failed; never guess a clicked face.
- ctx.conditions: optional saved UI supports/loads with faceKey/type/values. You may interpret these in code.
- ctx.selected_face: the selected original face key at submission, or None.
- ctx.describe(obj): public member names/types/doc strings to help inspect unfamiliar APIs. print(...) writes to returned stdout.
- ctx.generate_mesh(): calls Model.Mesh.GenerateMesh() and returns actual nodes/elements (32000 maximum).
  You set mesh controls before calling it. Mesh generation is NOT solving.
- ctx.solve(analysis): checks mesh limit, sets one CPU/no GPU, solves synchronously and requires Done.
  It records verified solve status, mesh counts and elapsed time. ALWAYS use this instead of .Solution.Solve.
- ctx.capture(result, name, label=None): evaluates an actual result, records its numeric extrema/units,
  and exports a PNG + text file. name must be a simple filename stem. E.g. ctx.capture(stress, 'stress_fine', 'Fine mesh stress').
- ctx.snapshot(name, label): exports the current Mechanical viewport (activate Mesh/Geometry first).
- ctx.table(name, rows): stores a list of dicts in the report and exports CSV/JSON, e.g. convergence rows.
- ctx.record(name, value, unit=None): stores computed/scalar findings. Do not fabricate measured values.
- ctx.save_project(name='model.mechdb'): saves inside this job. The harness also saves on completion.
- ctx.artifact(name): obtains a path INSIDE this job for Mechanical exports; no slashes or parent paths.

The worker returns stdout, traceback on error, actual geometry, all verified solves, extracted results,
tables/metrics and images. Each attempt is a fresh imported model, not a persistent interpreter.
Read errors, revise YOUR code and retry at most three code runs per user turn. Never resubmit an
uncertain transport job. No solve is performed just because the script finishes; report verifiedSolves.

Useful Mechanical syntax (examples of API calls, not a required workflow):
Model.AddStaticStructuralAnalysis(); Model.AddModalAnalysis(); analysis.Solution.AddTotalDeformation();
analysis.Solution.AddEquivalentStress(); analysis.AddFixedSupport(); analysis.AddForce();
force.DefineBy = LoadDefineBy.Components; force.XComponent.Output.DiscreteValues = [Quantity(100, 'N')]
load.Location = ctx.selection([...]); Model.Mesh.ElementSize = Quantity(3, 'mm');
Model.Mesh.ElementOrder = ElementOrder.Quadratic
For static settings use analysis.IAnalysisSettings; set LargeDeflection/WeakSprings explicitly from intent.
For remeshing use analysis.Solution.ClearGeneratedData(), Model.Mesh.ClearGeneratedData(), set a new
ElementSize, ctx.generate_mesh(), then ctx.solve(analysis). Do not recreate the same loads on each loop.
Set requested results BEFORE solving; evaluate after each solve and read .Maximum.Value/.Maximum.Unit.
For a mesh study record actual element size, node/element counts, max displacement/stress and relative
change versus the previous mesh. State the tolerance and whether it was actually met; non-monotonic
stress at fixed edges/corners may be singular. A few refinements are not proof of convergence everywhere.
Use ctx.describe for uncertain members, and inspect errors rather than assuming every API is supported.'''
