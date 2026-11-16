"""Project-local, post-processing-only adapter for cmuchancel/ansys-fluent-mcp.

Never changes the upstream checkout or Studio's simulation execution path.
"""
import atexit
import json
import os
from pathlib import Path
import sys
import threading
import uuid

# The live host's original adapter used absolute machine paths. This packaged
# copy resolves the same locations from the Studio configuration.
STUDIO = Path(os.environ.get('STUDIO_ROOT', Path(__file__).resolve().parents[2])).resolve()
_settings_path = STUDIO / '.env.local.json'
_settings = json.loads(_settings_path.read_text()) if _settings_path.is_file() else {}
WORKER = Path(_settings.get('FLUENT_REMOTE_DIR') or _settings.get('MECHANICAL_REMOTE_DIR') or STUDIO) / 'worker-data'
OUTPUT = STUDIO / 'gradio-data/exports/fluent-post'
os.environ.setdefault('AWP_ROOT261', r'C:\Program Files\ANSYS Inc\v261')
sys.path.insert(0, str(STUDIO))

# Load NumPy/PyFluent on the main thread before FastMCP dispatches synchronous tools.
import ansys.fluent.core as pyfluent
from ansys_fluent_mcp.server import build_server
from ansys_fluent_mcp.session import FluentSession, session_manager
from mechanical.ssh_worker import worker_lock

_mutex = threading.RLock()
_locks = {}


def open_session(file_path, version='3d', precision='double', processor_count=1):
    source = Path(file_path).resolve(strict=True)
    if not source.name.endswith('.cas.h5'):
        raise ValueError('Post-processing requires an existing .cas.h5 file.')
    data = source.with_name(source.name[:-7] + '.dat.h5')
    if not data.is_file():
        raise ValueError('The matching .dat.h5 file is required; no solve will be run.')
    if version not in ('2d', '3d') or precision not in ('single', 'double'):
        raise ValueError('Unsupported dimension or precision.')
    if processor_count != 1:
        raise ValueError('This post-processing adapter permits one CPU only.')
    with _mutex:
        if session_manager._sessions:
            raise ValueError('A post-processing session is already open; close it first.')
        lock = worker_lock(WORKER)
        lock.__enter__()
        solver = None
        try:
            sid = str(uuid.uuid4())
            directory = OUTPUT / sid
            directory.mkdir(parents=True)
            solver = pyfluent.launch_fluent(
                product_version='26.1.0', mode='solver', dimension=2 if version == '2d' else 3,
                precision=precision, processor_count=1, ui_mode='no_gui',
                graphics_driver='opengl2', cwd=str(directory), start_timeout=120)
            solver.settings.file.read_case_data(file_name=str(source))
            session = FluentSession(sid, solver, str(source), version, precision, 1)
            session_manager._sessions[sid] = session
            _locks[sid] = lock
            return session
        except BaseException:
            if solver is not None:
                try:
                    solver.exit()
                except Exception as exc:
                    # Retain a recoverable handle and exclusion if cleanup itself
                    # is uncertain; do not advertise that the worker is idle.
                    session_manager._sessions[sid] = FluentSession(sid, solver, str(source), version, precision, 1)
                    _locks[sid] = lock
                    raise ValueError('Post session cleanup is uncertain; close session '+sid+' before retrying.') from exc
            lock.__exit__(*sys.exc_info())
            raise


def close_session(session_id):
    with _mutex:
        session = session_manager.get_session(session_id)
        # If exit fails, retain session and lock: don't claim Fluent is closed.
        session.solver.exit()
        del session_manager._sessions[session_id]
        lock = _locks.pop(session_id)
        lock.__exit__(None, None, None)


session_manager.open_session = open_session
session_manager.close_session = close_session
atexit.register(session_manager.close_all)


def build_post_server():
    server = build_server()
    server.local_provider.remove_tool('execute_tui')
    server.instructions = '''Fluent post-processing only. Never runs a solve.
Use open_model with processor_count=1 and the approved existing case/data files.
One session is allowed; its worker lock prevents overlap with Studio execution.
Use get_project_info and list_view_targets, then set_display_target before rendering.
If no contours exist, create_contour with explicitly verified surface names.
Camera tools return native Fluent PNG image content; use these rather than web links.
get_camera_state logs applied operations, not live camera coordinates.
Close_model when finished to release Fluent and the worker lock.
This is separate from ansys-fluent API discovery and the bounded simulation worker.
'''

    @server.tool()
    def create_contour(session_id: str, name: str, field: str, surfaces: list[str]) -> dict:
        """Create a native post-processing contour, without modifying physics or solving.

        session_id: Session returned by open_model.
        name: New contour name; existing contours cannot be overwritten.
        field: pressure or velocity-magnitude.
        surfaces: Explicit live surface names, verified against the saved face mapping.
        """
        session = session_manager.get_session(session_id)
        if not name or field not in ('pressure', 'velocity-magnitude') or not surfaces:
            raise ValueError('Supply a name, supported field, and explicit surfaces.')
        solver = session.solver
        available = set(solver.fields.field_data.surfaces.allowed_values())
        if not set(surfaces) <= available:
            raise ValueError('Unknown surfaces; inspect get_project_info first.')
        contours = solver.settings.results.graphics.contour
        if name in contours.get_object_names():
            raise ValueError('Contour exists; choose a new name.')
        contours[name] = {'field': field, 'surfaces_list': surfaces, 'filled': True}
        return {'name': name, 'state': contours[name].get_state(), 'solved': False}

    return server


if __name__ == '__main__':
    OUTPUT.mkdir(parents=True, exist_ok=True)
    os.chdir(OUTPUT)
    build_post_server().run(transport='stdio')
