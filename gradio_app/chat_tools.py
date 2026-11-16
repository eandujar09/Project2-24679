"""Typed action boundary used by both the chatbot host and MCP tools."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field

class ActionArgs(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model_id: str
    revision: int

class Highlight(ActionArgs):
    face_keys: list[str] = Field(max_length=100)
    focus: bool = False

class CaptureViewport(ActionArgs):
    view: Literal['current', 'iso', 'top', 'bottom', 'front', 'back', 'left', 'right'] = 'current'

class PickViewportFace(ActionArgs):
    frame_id: str
    x: float = Field(ge=0, allow_inf_nan=False)
    y: float = Field(ge=0, allow_inf_nan=False)

class Analysis(ActionArgs):
    material: Literal['Structural Steel']
    small_deformation: Literal[True]
    element_size_mm: float = Field(default=3, ge=0.001, le=100000)

class Condition(ActionArgs):
    face_key: str
    kind: Literal['fixed', 'force', 'pressure', 'displacement', 'velocity_inlet', 'pressure_outlet', 'wall', 'symmetry', 'temperature', 'heat_flux', 'convection', 'radiation', 'adiabatic']
    values: dict[str, Annotated[float, Field(strict=True, allow_inf_nan=False)]] = Field(default_factory=dict)
    record_id: str | None = None

class MechanicalCode(ActionArgs):
    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=2000)
    code: str = Field(min_length=1, max_length=64000)


class FluentAPIQuery(ActionArgs):
    query: str = Field(min_length=1,max_length=2000)
    top_k: int = Field(default=5,ge=1,le=10,strict=True)
    under: str | None = Field(default=None,max_length=500)


class FluentAPIHelp(ActionArgs):
    path: str = Field(min_length=1,max_length=2000)


class FluentValidation(ActionArgs):
    code: str = Field(min_length=1,max_length=64000)


class FluentAnalysis(ActionArgs):
    domain: Literal['fluid-volume']
    regime: Literal['steady-laminar-incompressible']
    density: float = Field(gt=0, allow_inf_nan=False)
    dynamic_viscosity: float = Field(gt=0, allow_inf_nan=False)
    operating_pressure: float = Field(gt=0, allow_inf_nan=False)
    mesh_size_mm: float = Field(gt=0, allow_inf_nan=False)
    max_iterations: int = Field(ge=1, le=2000, strict=True)
    residual_tolerance: float = Field(gt=0, lt=1, allow_inf_nan=False)
    mass_imbalance_tolerance: float = Field(gt=0, lt=1, allow_inf_nan=False)


class SimulationIntent(ActionArgs):
    simulation_type: Literal['mechanical', 'heat_transfer', 'fluid']
    domain_status: Literal['existing', 'needs_added', 'unsure'] | None = None


class FluidDomain(ActionArgs):
    kind: Literal['existing', 'box', 'cylinder', 'custom']
    cad_role: Literal['fluid_volume', 'obstacle', 'reference']
    parameters: dict[str, Annotated[float, Field(strict=True, allow_inf_nan=False)]] = Field(default_factory=dict)
    description: str = Field(min_length=1, max_length=4000)


class DomainSuggestion(ActionArgs):
    clearance_mm: float | None = Field(default=None,gt=0,allow_inf_nan=False)
    fixed_axes: list[Literal['x','y','z']] = Field(default_factory=list,max_length=3)

class Remove(ActionArgs):
    record_id: str

class Comment(ActionArgs):
    face_key: str
    text: str = Field(min_length=1, max_length=20000)

ARGUMENT_MODELS = {'highlight_faces': Highlight, 'set_analysis': Analysis,
                   'apply_condition': Condition, 'remove_condition': Remove,
                   'add_comment': Comment, 'run_simulation': ActionArgs, 'run_mechanical_code': MechanicalCode, 'recover_mechanical_run': ActionArgs}
ARGUMENT_MODELS.update(capture_viewport=CaptureViewport, pick_viewport_face=PickViewportFace)
ARGUMENT_MODELS.update(set_fluent_analysis=FluentAnalysis, run_fluent_code=MechanicalCode,
                       recover_fluent_run=ActionArgs)
ARGUMENT_MODELS['set_simulation_intent'] = SimulationIntent
ARGUMENT_MODELS['set_fluid_domain'] = FluidDomain
ARGUMENT_MODELS.update(create_fluid_domain=ActionArgs,suggest_fluid_domain=DomainSuggestion)
ARGUMENT_MODELS.update(find_fluent_api=FluentAPIQuery,get_fluent_api_help=FluentAPIHelp,
    validate_fluent_api_code=FluentValidation,validate_fluent_program=FluentValidation,
    check_fluent_worker=ActionArgs,review_fluent_workflow=ActionArgs,render_fluent_results=ActionArgs)
DESCRIPTIONS = {
    'render_fluent_results':'Render native Fluent pressure/velocity boundary screenshots for the current completed, converged Fluent result through the isolated post-only MCP server. Does not rerun the simulation or modify saved physics. No arbitrary path arguments. Use after a successful result if native images are missing, not after uncertain jobs. Wall velocity is zero; these are not internal slices.',
    'review_fluent_workflow':'Read-only setup review and known-working authored native-STEP example. Returns missing inputs, unassigned face keys, saved assumptions, mesh/numerical guidance and exact example source. No setup changes or solver launch. Adapt it; do not treat example water/laminar assumptions as defaults.',
    'find_fluent_api':'Read-only discovery through the official Fluent MCP server. Search API paths before generating unfamiliar solver calls. Does not launch Fluent. Offline catalog may differ from worker Fluent 261.',
    'get_fluent_api_help':'Read-only official Fluent MCP help for a discovered path; no solver launch or mutation.',
    'validate_fluent_api_code':'Official Fluent MCP offline validation of a PyFluent snippet using solver/session globals. No execution. ctx/tasks/meshing/workflow are Studio globals, not upstream globals: validate underlying API snippets here and full Studio code with validate_fluent_program. parse_ok is not live compatibility or physics validation.',
    'validate_fluent_program':'Validate a full Studio execution program including ctx/tasks/meshing/workflow against the local bounded worker contract, without launching or submitting it. This is NOT MCP or live API validation. Use find_fluent_api/help and validate_fluent_api_code separately for underlying PyFluent calls.',
    'check_fluent_worker':'Read-only configured worker package/protocol compatibility check. Does not submit code, generate a mesh, launch Fluent or check out a license. A compatible worker is not proof of end-to-end solve success.',
    'create_fluid_domain': 'Construct the saved box/cylinder as real STEP CAD. obstacle role: subtract original solid CAD; reference role: explicit empty fluid volume. Requires positive obstacle clearance, valid watertight one-region output, volume and export checks. Activates a NEW derived model with NEW face keys and empty conditions; original CAD remains saved. Guided mode confirms construction separately. Custom/internal-passage capping is not implemented.',
    'suggest_fluid_domain': 'Read-only box-clearance proposal. Use when the user asks you to choose a positive gap or expand until no contact. Optional positive clearance_mm; otherwise proposes max(1 mm, 2% largest CAD span), ONLY a geometric gap. fixed_axes preserves saved min/max on those axes (e.g. y). Does not save/build anything or establish CFD adequacy. Show the proposal for confirmation rather than repeatedly asking for a number.',
    'set_fluid_domain': 'Save the user-defined domain before construction. existing: actual fluid_volume, parameters {}. box: min_x/y/z,max_x/y/z mm. cylinder: origin_x/y/z (start mm), axis_x/y/z (direction), radius,length mm. cad_role obstacle means subtract the CAD; reference means create empty volume. Then use create_fluid_domain for box/cylinder. custom definitions need separate preparation.',
    'set_simulation_intent': 'Record the user\'s simulation choice after upload: mechanical, heat_transfer, or fluid. For fluid also record domain_status existing, needs_added, or unsure once the user answers; do not restrict the domain to a box. Does not generate geometry or run a solver. Do not infer from CAD shape or a face click.',
    'set_fluent_analysis': 'Record OPTIONAL agreed steady laminar incompressible isothermal flow assumptions: density kg/m^3, viscosity Pa s, absolute operating pressure Pa, mesh size mm, iteration limit and residual/mass-balance tolerances. Saved values are binding inputs, not automatically applied physics or a prerequisite for agent-authored code. No physical defaults.',
    'run_fluent_code': 'Execute YOUR PyFluent Python in a fresh imported Fluent 261 worker, parallel to run_mechanical_code. Author mesh controls, region handling, models, materials, boundaries, initialization and results; no fixed setup template. Use ctx.generate_mesh/selection/solve for checked geometry and solving. Saved analysis/conditions are optional but binding if present. See Fluent runtime guide.',
    'recover_fluent_run': 'Recover the existing uncertain Fluent job without resubmitting or solving again.',
    'capture_viewport': 'When visual assistance is on, capture the CAD viewport as an image. Optionally change to a standard camera view. You can inspect the screenshot without clicking. The next model response receives the image plus its frame ID and pixel dimensions.',
    'pick_viewport_face': 'Resolve an (x,y) pixel in a specific screenshot to its exact visible CAD face and highlight it. Coordinates are screenshot pixels from the top-left, NOT screen coordinates. This uses the screenshot camera even if the live camera moved. Does not change user selection or apply a support/load.',
    'recover_mechanical_run': 'Check the existing program job after uncertain transport and retrieve completed results. Never submits or repeats code. If stillRunning, ask the user to check again later.',
    'run_mechanical_code': 'Write and execute your own PyMechanical Python for the current CAD. Fresh imported geometry; author analysis/mesh/material/loads/results/loops yourself. Returns actual logs, traceback, tables, images and verified solve status. See the supplied runtime guide. No fixed material or analysis type is required.',
    'highlight_faces': 'Highlight faces in violet without changing the user selection; empty list clears highlights. focus moves the camera.',
    'set_analysis': 'Record the agreed material, small-deformation assumption, and mesh size. Only Structural Steel is implemented.',
    'apply_condition': 'Apply one condition to one real face. Structural: fixed {}, force x/y/z N, displacement x/y/z mm, pressure magnitude MPa. Thermal: temperature {temperature} °C, heat_flux {magnitude} W/m² positive inward, convection {coefficient} W/(m² K) plus {ambient_temperature} °C, radiation {emissivity} 0..1 plus {ambient_temperature} °C, adiabatic {}. Fluid: velocity_inlet x/y/z m/s, pressure_outlet gauge_pressure Pa, wall {}, symmetry {}. To edit pass record_id.',
    'remove_condition': 'Remove one existing condition by its ID when the user requests it.',
    'add_comment': 'Attach the user\'s note to a face.',
    'run_simulation': 'Run the real remote Ansys solver once setup is complete. Returns actual report. Identical submissions are not repeated automatically.'}

def tool_schemas(visual_enabled=False):
    return [{'name': name, 'description': DESCRIPTIONS[name], 'arguments': model.model_json_schema()}
            for name, model in ARGUMENT_MODELS.items()
            if visual_enabled or name not in ('capture_viewport', 'pick_viewport_face')]

def apply_tool(service, sid, name, arguments):
    if name not in ARGUMENT_MODELS:
        raise ValueError('Unknown CAD tool: ' + str(name))
    validated = ARGUMENT_MODELS[name].model_validate(arguments).model_dump(exclude_none=True)
    return service.apply(sid, name, validated)
