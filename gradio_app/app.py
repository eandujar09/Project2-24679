"""Chat-driven CAD workspace. Run with python -m gradio_app.app."""
import argparse
from contextlib import asynccontextmanager
from functools import wraps
import os
from pathlib import Path
import hashlib

import gradio as gr
from .backend import Workspace
from .viewer import STATIC, cad_viewer
from .remote import check_connection
from .chat_state import ChatWorkspace
from .chat_agent import ChatAgent

CSS = '''
.gradio-container { max-width: 1560px !important; }
#cad-header { padding: 8px 0 4px; }
#cad-header h1 { font-size: 30px; letter-spacing: -0.7px; margin-bottom: 6px; }
#chat-panel { border: 1px solid var(--border-color-primary); border-radius: 14px; padding: 16px; }
#selection-context { min-height: 40px; padding: 8px 12px; border-radius: 8px; background: var(--background-fill-secondary); }
#chat-input textarea { font-size: 15px; }
.python-cad-viewer .cad-viewport { height: 600px; }
@media(max-width: 850px) { .python-cad-viewer .cad-viewport { height: 400px; } }
'''


def user_errors(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, OSError) as exc:
            raise gr.Error(str(exc)) from exc
    return wrapped


def build_app(workspace, service=None, chat_model=None):
    service = service or ChatWorkspace(workspace)
    agent = ChatAgent(service, chat_model)
    with gr.Blocks(title='CAD Simulation Studio', analytics_enabled=False) as app:
        sid = gr.State(value=None)
        seen = gr.State(-1)
        gr.Markdown('# Talk to your model\nSelect faces on the left. Build and run your simulation through the conversation on the right.', elem_id='cad-header')
        with gr.Row():
            with gr.Column(scale=6, min_width=420):
                with gr.Row():
                    upload = gr.File(label='Open STEP', file_types=['.step', '.stp'], type='filepath', height=110)
                    with gr.Column():
                        saved = gr.Dropdown(label='Saved models', choices=workspace.projects())
                        reopen = gr.Button('Open saved model', size='sm')
                viewer = cad_viewer()
                selection = gr.Markdown('No face selected.', elem_id='selection-context')
                gr.Markdown('**Amber:** your selection · **Violet:** assistant highlights · arrows and support symbols show saved conditions.')
                with gr.Accordion('Choose a face by number', open=False):
                    face = gr.Dropdown(label='Select whole CAD face', choices=[])
                    clear = gr.Button('Clear selection', size='sm')
                with gr.Accordion('Connection', open=False):
                    check = gr.Button('Check remote Ansys connection', size='sm')
                    connection_status = gr.Markdown('Ansys runs on your configured remote computer.')
            with gr.Column(scale=5, min_width=380, elem_id='chat-panel'):
                chat = gr.Chatbot(label='Simulation assistant', height=620, layout='bubble', buttons=['copy'])
                status = gr.Markdown('Ready · the assistant can write and run PyMechanical code')
                message = gr.Textbox(label='Message the assistant', placeholder='Analyze this bracket and compare mesh sizes…', lines=2, max_lines=5, max_length=8000, elem_id='chat-input')
                send = gr.Button('Send', variant='primary')
                artifacts = gr.File(label='Latest simulation · report, images, and Mechanical project', file_count='multiple', interactive=False, visible=False)
        timer = gr.Timer(0.8)
        read = gr.Button('Read CAD context', visible=False)
        context_json = gr.JSON(visible=False)
        outputs = [viewer, chat, selection, status, face, saved, artifacts, seen, send]

        def resolve_session(session_id, request=None):
            if session_id:
                return session_id  # Pure callback tests may supply an explicit session.
            if request is None or not request.session_hash:
                raise ValueError('Reload the app to establish a browser session.')
            return hashlib.sha256(request.session_hash.encode()).hexdigest()[:32]

        def initialize(session_id, request: gr.Request):
            return render(resolve_session(session_id, request))

        def render(session_id, status_text=None):
            with service.lock:
                s = service.session(session_id)
                p = workspace.get(s.model_id) if s.model_id else None
                selected = next((f for f in p['faces'] if f['key'] == s.selected), None) if p else None
                badge = (f'**Selected: Face {selected["index"]}** · {selected["areaMm2"]:.4g} mm² · The assistant can see this selection.'
                         if selected else '**No face selected.** Click the model to give the assistant a face reference.')
                if s.highlighted:
                    indices = [str(f['index']) for f in p['faces'] if f['key'] in s.highlighted]
                    badge += '  \nAssistant highlights: ' + ', '.join('Face ' + n for n in indices)
                history = []
                for item in s.messages:
                    content = item['content']
                    if isinstance(content, dict) and 'image' in content:
                        content = gr.Image(value=content['image'], label=content['label'], show_label=True, interactive=False, buttons=['download', 'fullscreen'])
                    elif isinstance(content, dict) and 'code' in content:
                        content = '**' + content['title'] + '**\n\n```python\n' + content['code'] + '\n```'
                    history.append({'role': item['role'], 'content': content})
                files = [s.result['archive']] if s.result and s.result.get('archive') else []
                if s.result and s.result.get('codeFile') and Path(s.result['codeFile']).is_file():
                    files.append(s.result['codeFile'])
                return (service.viewer(session_id), history, badge,
                        status_text or ('Running Ansys…' if s.running else 'Thinking…' if s.busy else 'Waiting for your confirmation' if s.pending_confirmation else 'Ready'),
                        gr.Dropdown(choices=[(f'Face {f["index"]} · {f["areaMm2"]:.3g} mm²', f['key']) for f in p['faces']] if p else [], value=s.selected),
                        gr.Dropdown(choices=workspace.projects(), value=s.model_id),
                        gr.update(value=files, visible=bool(files)), s.revision, gr.update(interactive=not s.busy))

        @user_errors
        def open_file(path, session_id, request: gr.Request = None):
            session_id = resolve_session(session_id, request)
            if not path:
                raise ValueError('Choose a STEP file first.')
            service.open_model(session_id, workspace.open_step(path))
            return render(session_id)

        @user_errors
        def open_saved(model_id, session_id, request: gr.Request = None):
            session_id = resolve_session(session_id, request)
            service.open_model(session_id, workspace.get(model_id))
            return render(session_id)

        @user_errors
        def select_face(key, session_id, request: gr.Request = None):
            session_id = resolve_session(session_id, request)
            s = service.session(session_id)
            service.select(session_id, s.model_id, key, focus=True)
            return render(session_id)

        @user_errors
        def pick_face(session_id, event: gr.EventData, request: gr.Request = None):
            session_id = resolve_session(session_id, request)
            data = event._data
            if not isinstance(data, dict) or data.get('modelId') != service.session(session_id).model_id:
                return tuple(gr.skip() for _ in outputs)
            service.select(session_id, data['modelId'], data.get('faceKey'))
            return render(session_id)

        def respond(text, session_id, request: gr.Request = None):
            session_id = resolve_session(session_id, request)
            if not text or not text.strip():
                yield tuple(gr.skip() for _ in [*outputs, message])
                return
            for state in agent.turn(session_id, text):
                yield (*render(session_id, state), '')

        def selection_turn(session_id, request: gr.Request = None):
            session_id = resolve_session(session_id, request)
            with service.lock:
                s = service.session(session_id)
                text = s.selection_event
                s.selection_event = None
            if text:
                yield from respond(text, session_id)
            else:
                yield tuple(gr.skip() for _ in [*outputs, message])

        def poll(session_id, last_seen, request: gr.Request = None):
            session_id = resolve_session(session_id, request)
            s = service.session(session_id)
            return tuple(gr.skip() for _ in outputs) if s.revision == last_seen else render(session_id)

        def clear_selection(session_id, request: gr.Request):
            return select_face(None, session_id, request)

        def read_context(session_id, request: gr.Request):
            session_id = resolve_session(session_id, request)
            service.session(session_id)
            return service.context(session_id)

        app.load(initialize, sid, outputs)
        upload.upload(open_file, [upload, sid], outputs, concurrency_id='cad-files', concurrency_limit=1)
        reopen.click(open_saved, [saved, sid], outputs, concurrency_id='cad-files', concurrency_limit=1)
        viewer.select(pick_face, sid, outputs, queue=False).then(selection_turn, sid, [*outputs, message], concurrency_limit=4)
        face.input(select_face, [face, sid], outputs, queue=False).then(selection_turn, sid, [*outputs, message], concurrency_limit=4)
        clear.click(clear_selection, sid, outputs, queue=False)
        send.click(respond, [message, sid], [*outputs, message], concurrency_limit=4)
        message.submit(respond, [message, sid], [*outputs, message], concurrency_limit=4)
        timer.tick(poll, [sid, seen], outputs, queue=False, show_progress='hidden')
        check.click(user_errors(check_connection), outputs=connection_status)
        read.click(read_context, sid, context_json, api_name='read_cad_context')
    app.cad_service = service
    return app


def build_server(workspace, chat_model=None, service=None, studio=True, auth=None, hosted_host=None):
    from fastapi import FastAPI
    from .mcp_server import build_mcp
    service = service or ChatWorkspace(workspace)
    mcp = build_mcp(service, hosted_host=hosted_host)
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    server = FastAPI(lifespan=lifespan)
    server.mount('/mcp', mcp_app)
    if studio:
        from .studio import install_studio
        install_studio(server, service, chat_model)
    demo = build_app(workspace, service, chat_model)
    demo.queue()
    server = gr.mount_gradio_app(server, demo, path='/', css=CSS,
             allowed_paths=[str(STATIC), str(workspace.root / 'previews'), str(workspace.root / 'exports')])
    server.state.cad_service = service
    if auth:
        from .hosting import PrivateDemoAuth
        server.add_middleware(PrivateDemoAuth, **auth)
    return server


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=7860)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--auth-config', help='Private JSON containing username/password; required outside loopback.')
    parser.add_argument('--data-dir', default=os.environ.get('STEP_GRADIO_DATA', 'gradio-data'))
    args = parser.parse_args()
    from .hosting import hosting_settings
    auth = hosting_settings(args.host, args.auth_config)
    uvicorn.run(build_server(Workspace(args.data_dir), auth=auth, hosted_host=args.host if auth else None),
                host=args.host, port=args.port)

if __name__ == '__main__':
    main()
