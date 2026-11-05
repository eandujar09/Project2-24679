"""Typed action boundary used by both the chatbot host and MCP tools."""
from typing import Literal
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
    kind: Literal['fixed', 'force', 'pressure', 'displacement']
    values: dict[str, float] = Field(default_factory=dict)
    record_id: str | None = None

class MechanicalCode(ActionArgs):
    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=2000)
    code: str = Field(min_length=1, max_length=64000)

class Remove(ActionArgs):
    record_id: str

class Comment(ActionArgs):
    face_key: str
    text: str = Field(min_length=1, max_length=20000)

ARGUMENT_MODELS = {'highlight_faces': Highlight, 'set_analysis': Analysis,
                   'apply_condition': Condition, 'remove_condition': Remove,
                   'add_comment': Comment, 'run_simulation': ActionArgs, 'run_mechanical_code': MechanicalCode, 'recover_mechanical_run': ActionArgs}
ARGUMENT_MODELS.update(capture_viewport=CaptureViewport, pick_viewport_face=PickViewportFace)
DESCRIPTIONS = {
    'capture_viewport': 'When visual assistance is on, capture the CAD viewport as an image. Optionally change to a standard camera view. You can inspect the screenshot without clicking. The next model response receives the image plus its frame ID and pixel dimensions.',
    'pick_viewport_face': 'Resolve an (x,y) pixel in a specific screenshot to its exact visible CAD face and highlight it. Coordinates are screenshot pixels from the top-left, NOT screen coordinates. This uses the screenshot camera even if the live camera moved. Does not change user selection or apply a support/load.',
    'recover_mechanical_run': 'Check the existing program job after uncertain transport and retrieve completed results. Never submits or repeats code. If stillRunning, ask the user to check again later.',
    'run_mechanical_code': 'Write and execute your own PyMechanical Python for the current CAD. Fresh imported geometry; author analysis/mesh/material/loads/results/loops yourself. Returns actual logs, traceback, tables, images and verified solve status. See the supplied runtime guide. No fixed material or analysis type is required.',
    'highlight_faces': 'Highlight faces in violet without changing the user selection; empty list clears highlights. focus moves the camera.',
    'set_analysis': 'Record the agreed material, small-deformation assumption, and mesh size. Only Structural Steel is implemented.',
    'apply_condition': 'Apply one condition to one real face. fixed: empty values. force: x/y/z in N. displacement: x/y/z in mm, all prescribed. pressure: magnitude in MPa (positive inward). To edit an existing condition, pass its record_id.',
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
