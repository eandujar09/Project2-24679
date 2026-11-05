"""Authoritative per-window CAD state shared by the chat host and MCP server."""
from dataclasses import dataclass, field
import hashlib
import json
from threading import RLock, Lock

from .simulation import prepare_request
from .remote import run_remote_project, run_remote_code, recover_job
from mechanical.contract import normalize_conditions


@dataclass
class CADSession:
    id: str
    model_id: str | None = None
    selected: str | None = None
    highlighted: list = field(default_factory=list)
    revision: int = 0
    focus_face: str | None = None
    focus_token: int = 0
    material: str | None = None
    small_deformation: bool | None = None
    element_size_mm: float = 3.0
    messages: list = field(default_factory=list)
    awaiting_selection: bool = False
    selection_event: str | None = None
    busy: bool = False
    running: bool = False
    last_fingerprint: str | None = None
    result: dict | None = None
    mechanical_export: dict | None = None
    exporting: bool = False
    error: str | None = None
    provider_session: str | None = None
    program_attempts: list = field(default_factory=list)
    gravity_loads: list = field(default_factory=list)
    pending_confirmation: dict | None = None
    interaction_mode: str = 'guided'
    visual_enabled: bool = False
    visual_frame: dict | None = None
    turn_lock: object = field(default_factory=Lock)


class ChatWorkspace:
    def __init__(self, workspace, runner=None, code_runner=None):
        self.workspace = workspace
        self.lock = RLock()
        self.sessions = {}
        self.runner = runner or run_remote_project
        self.code_runner = code_runner or run_remote_code
        from .visual import VisualBridge
        self.visual = VisualBridge(self)

    def preferences(self, sid, revision, interaction_mode, visual_enabled):
        with self.lock:
            s = self.existing(sid)
            if s.busy or s.running or s.turn_lock.locked():
                raise ValueError('Wait for the current turn before changing assistant settings.')
            if s.revision != revision:
                raise ValueError('The workspace changed. Try changing the setting again.')
            if interaction_mode not in ('guided', 'autonomous') or not isinstance(visual_enabled, bool):
                raise ValueError('Choose Guided or Autonomous mode and a visual assistance setting.')
            if (s.interaction_mode, s.visual_enabled) == (interaction_mode, visual_enabled):
                return
            s.interaction_mode, s.visual_enabled = interaction_mode, visual_enabled
            s.pending_confirmation = None
            s.awaiting_selection = False
            s.selection_event = None
            s.visual_frame = None
            s.provider_session = None
            s.revision += 1

    def session(self, session_id):
        if not isinstance(session_id, str) or len(session_id) != 32:
            raise ValueError('Invalid CAD session.')
        with self.lock:
            if session_id not in self.sessions:
                self.sessions[session_id] = CADSession(session_id, messages=[{
                    'role': 'assistant', 'content': 'Open a STEP model on the left, then tell me what you want to test. '
                    'You can click a face and refer to it as “this face.” I can highlight faces, set supports and loads, '
                    'and write PyMechanical code to inspect, analyze, or refine the mesh of your uploaded CAD. I’ll highlight and explain proposals, and wait for your confirmation before applying changes or running code.'}])
            return self.sessions[session_id]

    def existing(self, session_id):
        with self.lock:
            if session_id not in self.sessions:
                raise ValueError('CAD session not found. Open the app first.')
            return self.sessions[session_id]

    def add_message(self, sid, role, content):
        with self.lock:
            s = self.session(sid)
            s.messages.append({'role': role, 'content': content})
            s.revision += 1

    def open_model(self, sid, project):
        with self.lock:
            s = self.session(sid)
            if s.busy or s.running:
                raise ValueError('Wait for the current chat turn or simulation before switching models.')
            s.model_id = project['id']
            s.selected = None
            s.highlighted = []
            s.focus_face = None
            s.material = None
            s.small_deformation = None
            s.element_size_mm = 3.0
            s.result = None
            s.mechanical_export = None
            s.error = None
            s.last_fingerprint = None
            s.provider_session = None
            s.program_attempts = []
            s.gravity_loads = []
            s.pending_confirmation = None
            s.visual_frame = None
            s.messages = [{'role': 'assistant', 'content': f'Opened **{project["filename"]}** with {len(project["faces"])} faces. '
                           'What would you like to understand or test? I can identify faces and explain my interpretation. '
                           'I can generate and run PyMechanical code for this geometry, including mesh-refinement studies.'}]
            s.awaiting_selection = True
            s.selection_event = None
            s.revision += 1
            return s

    def select(self, sid, model_id, key, focus=False):
        with self.lock:
            s = self.session(sid)
            if model_id != s.model_id:
                return False
            if key:
                self.workspace.require_face(self.workspace.get(model_id), key)
            if s.selected == key:
                return False
            s.selected = key
            if focus:
                s.focus_face = key
                s.focus_token += 1
            s.revision += 1
            if s.awaiting_selection and key and not s.busy:
                face = next(f for f in self.workspace.get(model_id)['faces'] if f['key'] == key)
                s.selection_event = f'I selected Face {face["index"]} in the viewer.'
                s.awaiting_selection = False
            return True

    def missing(self, s, project):
        missing = []
        if not project:
            return ['Open a STEP model.']
        if s.material != 'Structural Steel':
            missing.append('Establish that the material is Structural Steel; other materials are not implemented.')
        if s.small_deformation is not True:
            missing.append('Establish that a linear static, small-deformation analysis is appropriate.')
        try:
            normalize_conditions(project['boundaryConditions'], {f['key'] for f in project['faces']})
        except ValueError as exc:
            missing.append(str(exc))
        return missing

    def context(self, sid):
        with self.lock:
            s = self.existing(sid)
            project = self.workspace.get(s.model_id) if s.model_id else None
            faces = project['faces'] if project else []
            compact = [{k: f[k] for k in ('key', 'index', 'areaMm2', 'centroidMm', 'normal', 'surfaceType', 'boundsMm') if k in f} for f in faces]
            return {'uri': f'cad://session/{sid}/context', 'sessionId': sid, 'revision': s.revision,
                    'modelId': s.model_id, 'filename': project['filename'] if project else None,
                    'selectedFace': next((f for f in faces if f['key'] == s.selected), None),
                    'highlightedFaceKeys': list(s.highlighted),
                    'executionMode': 'generated-python', 'faces': compact[:500], 'faceCount': len(faces), 'facesTruncated': len(faces) > 500,
                    'boundaryConditions': project['boundaryConditions'] if project else [],
                    'comments': project['comments'] if project else [],
                    'units': {'length': 'mm', 'force': 'N', 'pressure': 'MPa'},
                    'analysis': {'material': s.material, 'smallDeformation': s.small_deformation,
                                 'elementSizeMm': s.element_size_mm, 'type': 'linear static structural', 'solidCountSupported': 1},
                    'missingInformation': ['Open a STEP model.'] if not project else [],
                    'legacyPreset': {'missingInformation': self.missing(s, project)},
                    'programAttempts': [{k: a.get(k) for k in ('title', 'status', 'programSHA256', 'error', 'recoverable')} for a in s.program_attempts],
                    'simulationRunning': s.running, 'interactionMode': s.interaction_mode,
                    'gravityLoads': self.gravity(s),
                    'visualAssistance': self.visual.context(s),
                    'confirmationRequired': s.interaction_mode == 'guided',
                    'confirmationScope': 'built-in-chat',
                    'pendingConfirmation': ({'tool': s.pending_confirmation['tool'], 'summary': s.pending_confirmation['summary']} if s.pending_confirmation else None),
                    'lastResult': self.result_summary(s), 'lastError': s.error}

    def result_summary(self, s):
        if not s.result:
            return None
        report = s.result['report']
        return {key: report.get(key) for key in ('status', 'kind', 'title', 'modelId', 'jobId', 'results', 'mesh', 'messages', 'error', 'limitations', 'tables', 'metrics', 'verifiedSolves', 'geometry', 'stdout', 'traceback', 'errorStage', 'programSHA256', 'gravityLoads')}

    def gravity(self, s):
        from mechanical.gravity import preview_gravity
        from .chat_confirmations import state_fingerprint
        pending = s.pending_confirmation
        if (s.interaction_mode == 'guided' and pending and pending['tool'] == 'run_mechanical_code'
                and pending['fingerprint'] == state_fingerprint(self, s)):
            return [dict(row, state='proposed') for row in preview_gravity(pending['arguments']['code'])]
        return s.gravity_loads

    def viewer(self, sid):
        from .chat_confirmations import proposed_conditions
        with self.lock:
            s = self.session(sid)
            if not s.model_id:
                return ''
            return self.workspace.viewer_state(s.model_id, s.selected, highlighted=s.highlighted,
                       focus_face=s.focus_face, focusToken=s.focus_token, revision=s.revision, sessionId=sid,
                       proposedBoundaryConditions=proposed_conditions(self, s), gravityLoads=self.gravity(s))

    def _checked(self, sid, model_id, revision):
        s = self.existing(sid)
        if s.model_id != model_id or s.revision != revision:
            raise ValueError('The viewer state changed. Read the context resource again before acting.')
        if any(other.running and other.model_id == model_id for other in self.sessions.values()):
            raise ValueError('A simulation is running for this model. Wait for its result before changing its setup.')
        if not model_id:
            raise ValueError('Open a STEP model first.')
        return s, self.workspace.get(model_id)

    def apply(self, sid, tool, arguments):
        args = dict(arguments)
        if tool in ('capture_viewport', 'pick_viewport_face'):
            return self.visual.request(sid, tool, args)
        if tool == 'recover_mechanical_run':
            return self.recover_code(sid, args)
        if tool == 'run_mechanical_code':
            return self.execute_code(sid, args)
        if tool == 'read_context':
            return self.context(sid)
        with self.lock:
            model_id = args.pop('model_id', None)
            revision = args.pop('revision', None)
            s, project = self._checked(sid, model_id, revision)
            if tool == 'highlight_faces':
                keys = args.get('face_keys', [])
                if not isinstance(keys, list) or len(keys) > 100:
                    raise ValueError('Highlight at most 100 faces.')
                for key in keys:
                    self.workspace.require_face(project, key)
                s.highlighted = list(dict.fromkeys(keys))
                if args.get('focus') and keys:
                    s.focus_face = keys[0]
                    s.focus_token += 1
            elif tool == 'set_analysis':
                if args.get('material') != 'Structural Steel':
                    raise ValueError('Only Structural Steel is implemented. Do not substitute it for another material.')
                if args.get('small_deformation') is not True:
                    raise ValueError('Only a small-deformation linear static analysis is implemented.')
                size = args.get('element_size_mm', s.element_size_mm)
                if isinstance(size, bool) or not isinstance(size, (int, float)) or not 0.001 <= size <= 100000:
                    raise ValueError('Mesh size must be a finite positive number in mm.')
                if (s.material, s.small_deformation, s.element_size_mm) != ('Structural Steel', True, size):
                    s.result = None
                    s.error = None
                s.material, s.small_deformation, s.element_size_mm = 'Structural Steel', True, size
            elif tool == 'apply_condition':
                key, kind, values = args.get('face_key'), args.get('kind'), args.get('values', {})
                self.workspace.require_face(project, key)
                same = [r for r in project['boundaryConditions'] if r['faceKey'] == key]
                record_id = args.get('record_id')
                if record_id is None and any(r['type'] == kind for r in same):
                    raise ValueError('This face already has that condition type. Pass its record_id to update it instead of adding it twice.')
                if any(r['id'] != record_id and (kind in ('fixed', 'displacement') or r['type'] in ('fixed', 'displacement')) for r in same):
                    raise ValueError('This face already has a conflicting condition. Update or remove that condition explicitly.')
                self.workspace.save_annotation(model_id, key, 'boundaryConditions', {'type': kind, 'values': values}, record_id)
                s.highlighted = [key]
                s.result = None
                s.error = None
            elif tool == 'remove_condition':
                rid = args.get('record_id')
                if rid not in {r['id'] for r in project['boundaryConditions']}:
                    raise ValueError('Condition not found in the current model.')
                self.workspace.delete_annotation(model_id, 'boundaryConditions', rid, True)
                s.result = None
            elif tool == 'add_comment':
                self.workspace.save_annotation(model_id, args.get('face_key'), 'comments', {'text': args.get('text')})
            elif tool == 'run_simulation':
                missing = self.missing(s, project)
                if missing:
                    raise ValueError('Setup incomplete: ' + ' '.join(missing))
                # Preparing first verifies the exact CAD identity and solver contract.
                request = prepare_request(self.workspace, model_id, s.element_size_mm)
                fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
                if fingerprint == s.last_fingerprint:
                    if s.result:
                        return {'alreadyRun': True, 'result': self.result_summary(s)}
                    raise ValueError('This exact input was already submitted. Recover its previous job before trying again.')
                s.last_fingerprint = fingerprint
                s.running = True
                s.gravity_loads = []
                s.result = None
                s.error = None
            else:
                raise ValueError('Unknown CAD tool.')
            if tool in ('apply_condition', 'remove_condition', 'add_comment'):
                for other in self.sessions.values():
                    if other.id != sid and other.model_id == model_id:
                        other.revision += 1
                        if tool in ('apply_condition', 'remove_condition'):
                            other.result = None
                            other.error = None
            s.revision += 1
            if tool != 'run_simulation':
                return self.context(sid)
        # Do not hold the UI-state lock during a remote solve; selections remain live.
        try:
            result = self.runner(self.workspace, model_id, s.element_size_mm)
            with self.lock:
                s.result = result
                s.error = result['report'].get('error')
                return {'result': self.result_summary(s), 'artifactsReady': True}
        except Exception as exc:
            with self.lock:
                s.error = str(exc)
            raise
        finally:
            with self.lock:
                s.running = False
                s.revision += 1


    def execute_code(self, sid, args):
        from mechanical.program import validate_program
        from mechanical.gravity import preview_gravity
        program = {key: args[key] for key in ('title', 'objective', 'code')}
        digest = validate_program(program)
        with self.lock:
            s, project = self._checked(sid, args['model_id'], args['revision'])
            if any(a['status'] == 'unknown' for a in s.program_attempts):
                raise ValueError('A previous program has uncertain execution status. Recover that job before submitting new code.')
            selected_face = s.selected
            fingerprint = hashlib.sha256(json.dumps({'modelId': s.model_id, 'code': digest,
                           'conditions': project['boundaryConditions'], 'selectedFace': selected_face}, sort_keys=True).encode()).hexdigest()
            previous = next((a for a in s.program_attempts if a['fingerprint'] == fingerprint), None)
            if previous:
                if previous.get('report'):
                    if previous.get('result'):
                        s.result = previous['result']
                        s.error = previous['report'].get('error')
                        s.gravity_loads = [dict(row, state='applied') for row in previous['report'].get('gravityLoads') or []] if previous['status'] == 'succeeded' else []
                        s.revision += 1
                    return {'alreadyRun': True, 'result': previous['report']}
                raise ValueError('This exact program was already submitted. Recover its existing job before running it again.')
            attempt = {'title': program['title'], 'programSHA256': digest, 'fingerprint': fingerprint, 'status': 'running'}
            s.program_attempts.append(attempt)
            s.running, s.result, s.error = True, None, None
            s.gravity_loads = [dict(row, state='running') for row in preview_gravity(program['code'])]
            latest_code = next((m['content'] for m in reversed(s.messages) if isinstance(m['content'], dict) and 'code' in m['content']), None)
            if not latest_code or latest_code['code'] != program['code']:
                s.messages.append({'role': 'assistant', 'content': {'code': program['code'], 'title': program['title']}})
            s.messages.append({'role': 'assistant', 'content': '**Running generated Python:** ' + program['title']})
            s.revision += 1
            model_id = s.model_id
        try:
            result = self.code_runner(self.workspace, model_id, program, selected_face)
            with self.lock:
                s.result = result
                s.error = result['report'].get('error')
                s.gravity_loads = [dict(row, state='applied') for row in result['report'].get('gravityLoads', [])] if result['report']['status'] == 'succeeded' else []
                attempt.update(status=result['report']['status'], error=s.error, report=self.result_summary(s), result=result)
                return {'result': attempt['report'], 'artifactsReady': True}
        except Exception as exc:
            with self.lock:
                s.error = str(exc)
                s.gravity_loads = []
                attempt.update(status='unknown', error=s.error, recordPath=getattr(exc, 'record_path', None),
                               recoverable=bool(getattr(exc, 'record_path', None)))
            raise
        finally:
            with self.lock:
                s.running = False
                s.revision += 1


    def recover_code(self, sid, args):
        from pathlib import Path
        from mechanical.execution import result_files
        with self.lock:
            s, project = self._checked(sid, args['model_id'], args['revision'])
            attempt = next((a for a in reversed(s.program_attempts) if a['status'] == 'unknown'), None)
            if not attempt or not attempt.get('recordPath'):
                raise ValueError('There is no recoverable program job in this conversation.')
            path = Path(attempt['recordPath']).resolve()
            if not path.is_relative_to((self.workspace.root / 'exports' / 'simulations').resolve()):
                raise ValueError('The job record is outside this workspace.')
            s.running = True
            s.revision += 1
        try:
            status = recover_job(path, fetch=False)
            if status.get('status') == 'running':
                return {'stillRunning': True, 'jobId': status['jobId']}
            if status.get('status') == 'interrupted':
                return {'needsAttention': True, 'status': status}
            report = recover_job(path, fetch=True)
            with self.lock:
                s.result = result_files(path.parent, report)
                s.error = report.get('error')
                s.gravity_loads = [dict(row, state='applied') for row in report.get('gravityLoads', [])] if report['status'] == 'succeeded' else []
                attempt.update(status=report['status'], error=s.error, report=self.result_summary(s), result=s.result, recoverable=False)
                return {'recovered': True, 'result': self.result_summary(s), 'artifactsReady': True}
        finally:
            with self.lock:
                s.running = False
                s.revision += 1
