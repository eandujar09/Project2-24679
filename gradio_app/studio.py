"""HTTP presentation adapter for the Zoo-derived simulation frontend.

ChatWorkspace remains the authority for CAD state and ChatAgent owns every
engineering action, including confirmation. This module never executes tools.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .chat_agent import ChatAgent

STATIC = Path(__file__).with_name('studio_static')


class Message(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=8000)
    request_id: str = Field(min_length=1, max_length=80)
    proposal_token: str | None = None


class Selection(BaseModel):
    model_id: str
    face_key: str | None = None
    focus: bool = False


class OpenModel(BaseModel):
    model_id: str

class Preferences(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int
    interaction_mode: Literal['guided', 'autonomous']
    visual_enabled: bool

class ViewportResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model_id: str
    image: str | None = Field(default=None, max_length=6_000_000)
    face_key: str | None = None
    error: str | None = Field(default=None, max_length=500)


def install_studio(server, service, chat_model=None):
    agent = ChatAgent(service, chat_model)
    api = APIRouter(prefix='/api/studio')
    executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='studio-chat')
    active, statuses, accepted, files = set(), {}, {}, {}

    def existing(sid):
        try:
            return service.existing(sid)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    def proposal_token(session):
        pending = session.pending_confirmation
        return hashlib.sha256(json.dumps(pending, sort_keys=True).encode()).hexdigest() if pending else None

    def file_url(sid, value):
        path = Path(value).resolve()
        if not path.is_relative_to((service.workspace.root / 'exports').resolve()) or not path.is_file():
            return None
        key = hashlib.sha256(str(path).encode()).hexdigest()[:24]
        files.setdefault(sid, {})[key] = path
        return f'/api/studio/sessions/{sid}/files/{key}'

    def snapshot(sid):
        with service.lock:
            s = existing(sid)
            context = service.context(sid)
            viewer = json.loads(service.viewer(sid)) if s.model_id else None
            if viewer:
                viewer['geometryUrl'] = f'/api/studio/sessions/{sid}/geometry?model_id={s.model_id}'
            messages = []
            for message in s.messages:
                content = message['content']
                if isinstance(content, dict) and 'image' in content:
                    url = file_url(sid, content['image'])
                    content = {'image': url, 'label': content['label']} if url else {'unavailable': 'This historical image is no longer available.'}
                messages.append(dict(message, content=content))
            downloads = []
            if s.result:
                for key, label in [('archive', 'Download simulation'), ('codeFile', 'Python source')]:
                    if s.result.get(key):
                        url = file_url(sid, s.result[key])
                        if url:
                            downloads.append({'url': url, 'label': label, 'filename': Path(s.result[key]).name})
            return {'context': context, 'viewer': viewer, 'messages': messages,
                    'busy': s.busy or sid in active, 'proposalToken': proposal_token(s),
                    'status': statuses.get(sid, 'Thinking…') if sid in active else (
                        'Running Ansys…' if s.running else 'Review proposal' if s.pending_confirmation else 'Ready'),
                    'downloads': downloads,
                    'projects': [{'label': label, 'modelId': mid} for label, mid in service.workspace.projects()]}

    def run_turn(sid, message):
        try:
            for status in agent.turn(sid, message):
                with service.lock:
                    statuses[sid] = status
        except Exception as exc:
            service.add_message(sid, 'assistant', 'Could not finish this turn: ' + str(exc))
        finally:
            with service.lock:
                active.discard(sid)
                service.session(sid).busy = False
                service.session(sid).revision += 1

    def start_turn(sid, text, request_id, token=None):
        with service.lock:
            s = existing(sid)
            if request_id in accepted.setdefault(sid, set()):
                return
            if s.busy or s.running or sid in active:
                raise HTTPException(409, 'The assistant is still responding. Wait for this turn to finish.')
            if token is not None and token != proposal_token(s):
                raise HTTPException(409, 'That proposal has changed. Review the latest proposal before confirming.')
            if not text.strip():
                raise HTTPException(422, 'Enter a message first.')
            active.add(sid)
            s.busy = True
            s.revision += 1
            statuses[sid] = 'Thinking…'
            accepted[sid].add(request_id)
            executor.submit(run_turn, sid, text)

    @server.middleware('http')
    async def studio_origin(request: Request, call_next):
        if request.url.path.startswith('/api/studio') and request.method != 'GET':
            origin = request.headers.get('origin')
            if origin and urlparse(origin).netloc != request.headers.get('host'):
                from fastapi.responses import JSONResponse
                return JSONResponse({'detail': 'Use the app from its local address.'}, status_code=403)
        return await call_next(request)

    @api.post('/sessions')
    def create_session():
        sid = uuid.uuid4().hex
        service.session(sid)
        return snapshot(sid)

    @api.get('/sessions/{sid}')
    def read_session(sid: str):
        return snapshot(sid)

    @api.post('/sessions/{sid}/upload')
    def upload(sid: str, file: UploadFile):
        with service.lock:
            s = existing(sid)
            if s.busy or s.running:
                raise HTTPException(409, 'Wait for the current turn before opening a model.')
            name = Path((file.filename or '').replace('\\', '/')).name
            if Path(name).suffix.lower() not in ('.step', '.stp'):
                raise HTTPException(422, 'Choose a STEP file (.step or .stp).')
            try:
                with TemporaryDirectory(prefix='studio-upload-') as folder:
                    path = Path(folder) / name
                    size = 0
                    with path.open('wb') as stream:
                        while chunk := file.file.read(1024 * 1024):
                            size += len(chunk)
                            if size > 200 * 1024 * 1024:
                                raise HTTPException(413, 'This file exceeds the 200 MB upload limit.')
                            stream.write(chunk)
                    service.open_model(sid, service.workspace.open_step(path))
            except (ValueError, OSError) as exc:
                raise HTTPException(422, str(exc)) from exc
        return snapshot(sid)

    @api.post('/sessions/{sid}/open')
    def open_saved(sid: str, body: OpenModel):
        existing(sid)
        try:
            service.open_model(sid, service.workspace.get(body.model_id))
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return snapshot(sid)

    @api.post('/sessions/{sid}/select')
    def select(sid: str, body: Selection):
        with service.lock:
            s = existing(sid)
            if s.model_id != body.model_id:
                raise HTTPException(409, 'The model changed. Select a face in the current model.')
            try:
                service.select(sid, body.model_id, body.face_key, focus=body.focus)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            event, s.selection_event = s.selection_event, None
            if event:
                start_turn(sid, event, uuid.uuid4().hex)
        return snapshot(sid)

    @api.post('/sessions/{sid}/messages', status_code=202)
    def message(sid: str, body: Message):
        start_turn(sid, body.text, body.request_id, body.proposal_token)
        return snapshot(sid)

    @api.post('/sessions/{sid}/preferences')
    def preferences(sid: str, body: Preferences):
        existing(sid)
        try:
            service.preferences(sid, **body.model_dump())
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return snapshot(sid)

    @api.post('/sessions/{sid}/visual/{request_id}')
    def viewport_response(sid: str, request_id: str, body: ViewportResponse):
        existing(sid)
        try:
            service.visual.respond(sid, request_id, body.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {'accepted': True}

    @api.post('/sessions/{sid}/clear')
    def clear(sid: str):
        with service.lock:
            s = existing(sid)
            if s.busy or s.running:
                raise HTTPException(409, 'Wait for the current turn before starting a new conversation.')
            # Keep result/attempt records: clearing chat must not allow uncertain
            # jobs or duplicate code to be silently submitted again.
            s.messages = []
            s.provider_session = None
            s.pending_confirmation = None
            s.awaiting_selection = False
            s.selection_event = None
            service.add_message(sid, 'assistant', 'What would you like to test? Your model and saved simulation setup are still here.')
        return snapshot(sid)

    @api.get('/sessions/{sid}/geometry')
    def geometry(sid: str, model_id: str):
        with service.lock:
            if existing(sid).model_id != model_id:
                raise HTTPException(409, 'The model changed.')
            service.viewer(sid)  # Creates the exact, mapped geometry cache.
            path = service.workspace.root / 'previews' / (model_id + '-viewer.json')
        return FileResponse(path, media_type='application/json')

    @api.get('/sessions/{sid}/files/{key}')
    def artifact(sid: str, key: str):
        existing(sid)
        path = files.get(sid, {}).get(key)
        if not path or not path.is_file():
            raise HTTPException(404, 'This result file is no longer available.')
        return FileResponse(path, filename=path.name, content_disposition_type='inline')

    @api.get('/sessions/{sid}/annotations')
    def annotations(sid: str):
        s = existing(sid)
        if not s.model_id:
            raise HTTPException(422, 'Open a CAD model first.')
        return service.workspace.project_snapshot(s.model_id)

    @api.post('/connection')
    def connection():
        from .remote import check_connection
        try:
            return {'message': check_connection()}
        except (ValueError, OSError) as exc:
            raise HTTPException(503, str(exc)) from exc

    server.include_router(api)
    if STATIC.is_dir():
        server.mount('/studio-assets', StaticFiles(directory=STATIC / 'studio-assets'), name='studio-assets')

    @server.get('/', include_in_schema=False)
    def index():
        if not (STATIC / 'index.html').is_file():
            raise HTTPException(503, 'Build the frontend with npm run build:studio.')
        return FileResponse(STATIC / 'index.html', headers={'Cache-Control': 'no-cache'})

    return snapshot
