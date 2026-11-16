"""Real MCP resources and tools backed by the same state used by the CAD/chat UI."""
import json
import base64
from functools import partial
from typing import Literal
import anyio
from mcp.server.fastmcp import FastMCP
from .chat_tools import apply_tool


def build_mcp(service, hosted_host=None):
    from mcp.server.transport_security import TransportSecuritySettings
    transport_security = None
    if hosted_host:
        hosts = ['127.0.0.1:*', 'localhost:*', f'{hosted_host}:*']
        transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=hosts,
            allowed_origins=[f'http://{host}' for host in hosts])
    mcp = FastMCP('CAD Simulation Studio', host='127.0.0.1', streamable_http_path='/',
                  stateless_http=True, json_response=True,
                  transport_security=transport_security,
                  instructions='Read cad://sessions, then the relevant session context. Mutations require its modelId and revision. Selection and assistant highlights are independent.')

    @mcp.resource('cad://sessions', mime_type='application/json')
    def sessions() -> str:
        """Open CAD windows and their resource URIs. This server is local to this Mac."""
        with service.lock:
            return json.dumps([{'sessionId': s.id, 'modelId': s.model_id,
                                'contextUri': f'cad://session/{s.id}/context'} for s in service.sessions.values()])

    @mcp.resource('cad://models', mime_type='application/json')
    def saved_models() -> str:
        """Saved CAD models available to open in an app window."""
        return json.dumps([{'label': label, 'modelId': model_id}
                           for label, model_id in service.workspace.projects()])

    @mcp.tool()
    async def open_saved_model(session_id: str, model_id: str, revision: int) -> dict:
        """Open a model from cad://models in a specific app window. Read that window's context revision first."""
        def open_model():
            with service.lock:
                session = service.existing(session_id)
                if session.revision != revision:
                    raise ValueError('The viewer state changed. Read the context resource again before opening a model.')
                project = service.workspace.get(model_id)
                service.open_model(session_id, project)
                return service.context(session_id)
        return await anyio.to_thread.run_sync(open_model)

    @mcp.resource('cad://session/{session_id}/context', mime_type='application/json')
    def cad_context(session_id: str) -> str:
        """Current model, selected face, highlighted faces, conditions, analysis and result status. Read again before each action."""
        return json.dumps(service.context(session_id), allow_nan=False)

    @mcp.resource('cad://session/{session_id}/faces/{offset}', mime_type='application/json')
    def cad_faces(session_id: str, offset: int) -> str:
        """Read a page of 100 exact face descriptors from the open model."""
        with service.lock:
            s = service.existing(session_id)
            if offset < 0:
                raise ValueError('Offset must be nonnegative.')
            faces = service.workspace.get(s.model_id)['faces']
            return json.dumps({'modelId': s.model_id, 'revision': s.revision, 'offset': offset,
                               'total': len(faces), 'faces': faces[offset:offset + 100]})

    async def apply(sid, name, args):
        return await anyio.to_thread.run_sync(partial(apply_tool, service, sid, name, args))

    @mcp.tool()
    async def highlight_faces(session_id: str, model_id: str, revision: int, face_keys: list[str], focus: bool = False) -> dict:
        """Highlight faces without changing the user's selection. An empty list clears highlights."""
        return await apply(session_id, 'highlight_faces', dict(model_id=model_id, revision=revision, face_keys=face_keys, focus=focus))

    @mcp.tool()
    async def set_analysis(session_id: str, model_id: str, revision: int, material: Literal['Structural Steel'], small_deformation: bool, element_size_mm: float = 3) -> dict:
        """Record analysis assumptions established in the conversation; unsupported materials are rejected."""
        return await apply(session_id, 'set_analysis', dict(model_id=model_id, revision=revision, material=material,
                           small_deformation=small_deformation, element_size_mm=element_size_mm))

    @mcp.tool()
    async def apply_condition(session_id: str, model_id: str, revision: int, face_key: str,
                              kind: Literal['fixed', 'force', 'pressure', 'displacement', 'velocity_inlet', 'pressure_outlet', 'wall', 'symmetry', 'temperature', 'heat_flux', 'convection', 'radiation', 'adiabatic'], values: dict[str, float], record_id: str | None = None) -> dict:
        """Apply a structural, fluid or thermal condition to a real face. Read cad://runtime for exact fields and units; supply record_id to edit."""
        return await apply(session_id, 'apply_condition', dict(model_id=model_id, revision=revision, face_key=face_key,
                           kind=kind, values=values, record_id=record_id))

    @mcp.tool()
    async def remove_condition(session_id: str, model_id: str, revision: int, record_id: str) -> dict:
        """Remove one condition the user has requested to remove."""
        return await apply(session_id, 'remove_condition', dict(model_id=model_id, revision=revision, record_id=record_id))

    @mcp.tool()
    async def add_comment(session_id: str, model_id: str, revision: int, face_key: str, text: str) -> dict:
        """Attach a user note to the specified face."""
        return await apply(session_id, 'add_comment', dict(model_id=model_id, revision=revision, face_key=face_key, text=text))

    @mcp.tool()
    async def run_mechanical_code(session_id: str, model_id: str, revision: int, title: str, objective: str, code: str) -> dict:
        """Execute model-authored PyMechanical Python for this exact CAD in a fresh remote job. Read cad://runtime for the API contract. Returns actual stdout, errors, tables and solve results."""
        return await apply(session_id, 'run_mechanical_code', dict(model_id=model_id, revision=revision,
                           title=title, objective=objective, code=code))

    @mcp.tool()
    async def recover_mechanical_run(session_id: str, model_id: str, revision: int) -> dict:
        """Check/retrieve the existing uncertain program job without submitting another solve."""
        return await apply(session_id, 'recover_mechanical_run', dict(model_id=model_id, revision=revision))

    @mcp.resource('cad://runtime', mime_type='text/plain')
    def runtime_guide() -> str:
        from mechanical.program import PROGRAM_GUIDE
        from fluent.program import PROGRAM_GUIDE as FLUENT_GUIDE
        from .thermal import RUNTIME_GUIDE
        return PROGRAM_GUIDE + '\n' + FLUENT_GUIDE + '\n' + RUNTIME_GUIDE

    @mcp.tool()
    async def suggest_fluid_domain(session_id: str, model_id: str, revision: int,
                                     clearance_mm: float | None = None, fixed_axes: list[str] | None = None) -> dict:
        """Read-only box-gap proposal. Preserve user-fixed axes. A geometric gap is not CFD-domain adequacy."""
        return await apply(session_id,'suggest_fluid_domain',dict(model_id=model_id,revision=revision,
                           clearance_mm=clearance_mm,fixed_axes=fixed_axes or []))

    @mcp.tool()
    async def create_fluid_domain(session_id: str, model_id: str, revision: int) -> dict:
        """Build the saved box/cylinder, subtract an obstacle when specified, validate and activate derived fluid CAD. New face keys, no inherited conditions. Direct MCP requires trusted-controller approval."""
        return await apply(session_id,'create_fluid_domain',dict(model_id=model_id,revision=revision))

    @mcp.tool()
    async def set_simulation_intent(session_id: str, model_id: str, revision: int,
                                     simulation_type: Literal['mechanical','heat_transfer','fluid'],
                                     domain_status: Literal['existing','needs_added','unsure'] | None = None) -> dict:
        """Record the user's simulation choice. Does not generate CAD or apply physics."""
        return await apply(session_id,'set_simulation_intent',dict(model_id=model_id,revision=revision,
                           simulation_type=simulation_type,domain_status=domain_status))

    @mcp.tool()
    async def set_fluid_domain(session_id: str, model_id: str, revision: int,
                                kind: Literal['existing','box','cylinder','custom'],
                                cad_role: Literal['fluid_volume','obstacle','reference'],
                                parameters: dict[str,float], description: str) -> dict:
        """Save domain technique and mm dimensions, then use create_fluid_domain for box/cylinder CAD construction."""
        return await apply(session_id,'set_fluid_domain',dict(model_id=model_id,revision=revision,
                           kind=kind,cad_role=cad_role,parameters=parameters,description=description))

    @mcp.tool()
    async def set_fluent_analysis(session_id: str, model_id: str, revision: int,
                                  domain: Literal['fluid-volume'], regime: Literal['steady-laminar-incompressible'],
                                  density: float, dynamic_viscosity: float, operating_pressure: float,
                                  mesh_size_mm: float, max_iterations: int, residual_tolerance: float,
                                  mass_imbalance_tolerance: float) -> dict:
        """Record optional saved laminar-flow assumptions, not a required setup template. See cad://runtime. Direct MCP is trusted-controller access."""
        args = dict(model_id=model_id, revision=revision, domain=domain, regime=regime,
                    density=density, dynamic_viscosity=dynamic_viscosity, operating_pressure=operating_pressure,
                    mesh_size_mm=mesh_size_mm, max_iterations=max_iterations, residual_tolerance=residual_tolerance,
                    mass_imbalance_tolerance=mass_imbalance_tolerance)
        return await apply(session_id, 'set_fluent_analysis', args)

    @mcp.tool()
    async def run_fluent_code(session_id: str, model_id: str, revision: int, title: str, objective: str, code: str) -> dict:
        """Execute agent-authored mesh/physics/setup code in a fresh imported Fluent worker, like run_mechanical_code. Fixed ctx.mesh/configure are removed. Read cad://runtime first."""
        return await apply(session_id, 'run_fluent_code', dict(model_id=model_id, revision=revision,
                            title=title, objective=objective, code=code))

    @mcp.tool()
    async def find_fluent_api(session_id:str,model_id:str,revision:int,query:str,top_k:int=5,under:str|None=None)->dict:
        """Read-only discovery through official Fluent MCP; does not launch a solver."""
        args=dict(model_id=model_id,revision=revision,query=query,top_k=top_k)
        if under is not None:args['under']=under
        return await apply(session_id,'find_fluent_api',args)

    @mcp.tool()
    async def get_fluent_api_help(session_id:str,model_id:str,revision:int,path:str)->dict:
        """Read-only official Fluent MCP help for a discovered API path."""
        return await apply(session_id,'get_fluent_api_help',dict(model_id=model_id,revision=revision,path=path))

    @mcp.tool()
    async def validate_fluent_api_code(session_id:str,model_id:str,revision:int,code:str)->dict:
        """Official Fluent MCP offline snippet validation; solver/session globals, not Studio ctx globals."""
        return await apply(session_id,'validate_fluent_api_code',dict(model_id=model_id,revision=revision,code=code))

    @mcp.tool()
    async def validate_fluent_program(session_id:str,model_id:str,revision:int,code:str)->dict:
        """Local worker-contract validation of full Studio code. Not MCP/live-API validation; no execution."""
        return await apply(session_id,'validate_fluent_program',dict(model_id=model_id,revision=revision,code=code))

    @mcp.tool()
    async def render_fluent_results(session_id:str,model_id:str,revision:int)->dict:
        """Native MCP contours of this session's converged Fluent result, without another solve."""
        return await apply(session_id,'render_fluent_results',dict(model_id=model_id,revision=revision))

    @mcp.tool()
    async def review_fluent_workflow(session_id:str,model_id:str,revision:int)->dict:
        """Read-only Fluent readiness review and reference authored code; never runs or changes physics."""
        return await apply(session_id,'review_fluent_workflow',dict(model_id=model_id,revision=revision))

    @mcp.tool()
    async def check_fluent_worker(session_id:str,model_id:str,revision:int)->dict:
        """Check configured worker package/protocol compatibility without solver launch or submission."""
        return await apply(session_id,'check_fluent_worker',dict(model_id=model_id,revision=revision))

    @mcp.tool()
    async def recover_fluent_run(session_id: str, model_id: str, revision: int) -> dict:
        """Retrieve the existing uncertain Fluent job; never submit a replacement."""
        return await apply(session_id, 'recover_fluent_run', dict(model_id=model_id, revision=revision))

    @mcp.resource('cad://session/{session_id}/viewport', mime_type='image/png')
    def viewport_image(session_id: str) -> bytes:
        """Latest current viewport screenshot, available only with Visual assistance enabled."""
        with service.lock:
            frame = service.visual.frame(service.existing(session_id))
            if not frame:
                raise ValueError('No current screenshot. Enable Visual assistance and capture the viewport.')
            return base64.b64decode(frame['image'].split(',', 1)[1])

    @mcp.tool()
    async def capture_viewport(session_id: str, model_id: str, revision: int,
                               view: Literal['current', 'iso', 'top', 'bottom', 'front', 'back', 'left', 'right'] = 'current'):
        """See the CAD viewport without clicking. Requires Visual assistance and an open Studio tab. Returns PNG plus frame ID and pixel dimensions."""
        from mcp.types import TextContent, ImageContent
        result = await apply(session_id, 'capture_viewport', dict(model_id=model_id, revision=revision, view=view))
        with service.lock:
            frame = service.visual.frame(service.existing(session_id))
            if not frame or frame['id'] != result['frameId']:
                raise ValueError('The viewport changed. Capture it again.')
            return [TextContent(type='text', text=json.dumps(result)),
                    ImageContent(type='image', mimeType='image/png', data=frame['image'].split(',', 1)[1])]

    @mcp.tool()
    async def pick_viewport_face(session_id: str, model_id: str, revision: int,
                                 frame_id: str, x: float, y: float) -> dict:
        """Map a pixel in the captured image to an exact CAD face and highlight it. Uses the captured camera. Does not change the user's selection or apply a condition."""
        return await apply(session_id, 'pick_viewport_face', dict(model_id=model_id, revision=revision,
                           frame_id=frame_id, x=x, y=y))

    @mcp.tool()
    async def run_simulation(session_id: str, model_id: str, revision: int) -> dict:
        """Run the real Ansys backend once enough information is established. Do not resubmit an uncertain job."""
        return await apply(session_id, 'run_simulation', dict(model_id=model_id, revision=revision))

    return mcp
