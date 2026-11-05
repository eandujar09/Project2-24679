"""Real MCP resources and tools backed by the same state used by the CAD/chat UI."""
import json
from functools import partial
from typing import Literal
import anyio
from mcp.server.fastmcp import FastMCP
from .chat_tools import apply_tool


def build_mcp(service):
    mcp = FastMCP('CAD Simulation Studio', host='127.0.0.1', streamable_http_path='/',
                  stateless_http=True, json_response=True,
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
                              kind: Literal['fixed', 'force', 'pressure', 'displacement'], values: dict[str, float], record_id: str | None = None) -> dict:
        """Apply a support/load to a real face. Force x/y/z are N, displacement mm, pressure magnitude MPa (positive inward). Supply record_id to edit."""
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
        return PROGRAM_GUIDE

    @mcp.tool()
    async def run_simulation(session_id: str, model_id: str, revision: int) -> dict:
        """Run the real Ansys backend once enough information is established. Do not resubmit an uncertain job."""
        return await apply(session_id, 'run_simulation', dict(model_id=model_id, revision=revision))

    return mcp
