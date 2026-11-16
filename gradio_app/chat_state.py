"""Authoritative per-window CAD state shared by the chat host and MCP server."""
from dataclasses import dataclass, field
import hashlib
import json
import uuid
from threading import RLock, Lock

from .simulation import prepare_request
from .remote import run_remote_project, run_remote_code, run_remote_fluent_code, recover_job, definite_non_submission
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
    awaiting_simulation_choice: bool = False
    selection_event: str | None = None
    busy: bool = False
    running: bool = False
    domain_building: bool = False
    last_fingerprint: str | None = None
    result: dict | None = None
    mechanical_export: dict | None = None
    exporting: bool = False
    error: str | None = None
    provider_session: str | None = None
    program_attempts: list = field(default_factory=list)
    gravity_loads: list = field(default_factory=list)
    pending_confirmation: dict | None = None
    question: dict | None = None
    interaction_mode: str = 'guided'
    visual_enabled: bool = False
    visual_frame: dict | None = None
    turn_lock: object = field(default_factory=Lock)


class ChatWorkspace:
    def __init__(self, workspace, runner=None, code_runner=None, fluent_runner=None):
        self.workspace = workspace
        self.lock = RLock()
        self.sessions = {}
        self.runner = runner or run_remote_project
        self.code_runner = code_runner or run_remote_code
        self.fluent_runner = fluent_runner or run_remote_fluent_code
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
            s.question = None
            s.revision += 1

    def session(self, session_id):
        if not isinstance(session_id, str) or len(session_id) != 32:
            raise ValueError('Invalid CAD session.')
        with self.lock:
            if session_id not in self.sessions:
                self.sessions[session_id] = CADSession(session_id, messages=[{
                    'role': 'assistant', 'content': 'Upload a STEP model to begin.'}])
            return self.sessions[session_id]

    def existing(self, session_id):
        with self.lock:
            if session_id not in self.sessions:
                raise ValueError('CAD session not found. Open the app first.')
            return self.sessions[session_id]

    def add_message(self, sid, role, content, details=None, choices=None, multiple=False, scope='state'):
        with self.lock:
            s = self.session(sid)
            row = {'id':uuid.uuid4().hex,'role':role,'content':content}
            if details:
                row['details'] = details
            if choices:
                from .chat_presentation import Choice
                from .chat_confirmations import state_fingerprint
                if not isinstance(choices,list) or not 1 <= len(choices) <= 8:
                    raise ValueError('Offer one to eight selection options.')
                options = [dict(Choice.model_validate(c).model_dump(),id=str(i)) for i,c in enumerate(choices)]
                if len({c['label'] for c in options}) != len(options):
                    raise ValueError('Choice labels must be distinct.')
                if not s.model_id:
                    scope = 'model'
                question = {'token':uuid.uuid4().hex,'modelId':s.model_id,'choices':options,
                            'multiple':bool(multiple),'scope':scope,
                            'fingerprint':state_fingerprint(self,s) if scope == 'state' else None}
                s.question = question
                row['question'] = {k:v for k,v in question.items() if k not in ('fingerprint','scope')}
            s.messages.append(row)
            s.revision += 1

    def current_question(self,s):
        from .chat_confirmations import state_fingerprint
        q = s.question
        if not q or q['modelId'] != s.model_id:
            return None
        if q['scope'] == 'state' and q['fingerprint'] != state_fingerprint(self,s):
            return None
        return {k:v for k,v in q.items() if k not in ('fingerprint','scope')}

    def choice_text(self,sid,token,ids):
        with self.lock:
            q = self.current_question(self.existing(sid))
            if not q or q['token'] != token:
                raise ValueError('That question is no longer current. Use the latest question or type your answer.')
            if not ids or len(set(ids)) != len(ids) or (not q['multiple'] and len(ids) != 1):
                raise ValueError('Select the requested number of options.')
            choices = {c['id']:c for c in q['choices']}
            if any(i not in choices for i in ids):
                raise ValueError('Unknown selection option.')
            return '; '.join(choices[i]['value'] for i in ids)

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
            s.question = None
            s.visual_frame = None
            from .chat_presentation import PHYSICS_CHOICES
            s.messages = []
            self.add_message(sid,'assistant','Is this a mechanical, heat transfer, or fluid dynamics simulation?',
                             details=f'Opened **{project["filename"]}** with {len(project["faces"])} original CAD faces.',
                             choices=PHYSICS_CHOICES,scope='model')
            s.awaiting_selection = False
            s.awaiting_simulation_choice = True
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
            from fluent.contract import KINDS
            from .thermal import KINDS as THERMAL_KINDS
            normalize_conditions([r for r in project['boundaryConditions'] if r['type'] not in KINDS | THERMAL_KINDS], {f['key'] for f in project['faces']})
        except ValueError as exc:
            missing.append(str(exc))
        return missing

    def context(self, sid):
        with self.lock:
            s = self.existing(sid)
            project = self.workspace.get(s.model_id) if s.model_id else None
            faces = project['faces'] if project else []
            compact = [{k: f[k] for k in ('key', 'index', 'areaMm2', 'centroidMm', 'normal', 'surfaceType', 'boundsMm', 'boundaryRole') if k in f} for f in faces]
            return {'uri': f'cad://session/{sid}/context', 'sessionId': sid, 'revision': s.revision,
                    'modelId': s.model_id, 'filename': project['filename'] if project else None,
                    'selectedFace': next((f for f in faces if f['key'] == s.selected), None),
                    'highlightedFaceKeys': list(s.highlighted),
                    'executionMode': 'generated-python', 'faces': compact[:500], 'faceCount': len(faces), 'facesTruncated': len(faces) > 500,
                    'boundaryConditions': project['boundaryConditions'] if project else [],
                    'availableSolvers': ['mechanical', 'fluent'],
                    'simulationIntent': project.get('simulationIntent') if project else None,
                    'awaitingSimulationChoice': s.awaiting_simulation_choice,
                    'question': self.current_question(s),
                    'fluidDomain': project.get('fluidDomain') if project else None,
                    'domainGeneration': ({k:v for k,v in project['domainGeneration'].items() if k != 'artifactDirectory'} if project and project.get('domainGeneration') else None),
                    'fluentAnalysis': project.get('fluentAnalysis') if project else None,
                    'fluentScope': 'Agent-authored mesh and physical setup, like Mechanical. Checked steady-flow solves in one fluid-volume CAD; optional saved assumptions remain binding. No automatic FSI.',
                    'comments': project['comments'] if project else [],
                    'units': {'length': 'mm', 'force': 'N', 'pressure': 'MPa'},
                    'thermalUnits': {'temperature': '°C', 'heatFlux': 'W/m²', 'convectionCoefficient': 'W/(m² K)'},
                    'analysis': {'material': s.material, 'smallDeformation': s.small_deformation,
                                 'elementSizeMm': s.element_size_mm, 'type': 'linear static structural', 'solidCountSupported': 1},
                    'missingInformation': ['Open a STEP model.'] if not project else [],
                    'legacyPreset': {'missingInformation': self.missing(s, project)},
                    'programAttempts': [{k: a.get(k) for k in ('title', 'status', 'programSHA256', 'error', 'recoverable','submissionState','retryable')} for a in s.program_attempts],
                    'simulationRunning': s.running and not s.domain_building, 'geometryBuilding':s.domain_building,
                    'interactionMode': s.interaction_mode,
                    'gravityLoads': self.gravity(s),
                    'visualAssistance': self.visual.context(s),
                    'confirmationRequired': s.interaction_mode == 'guided',
                    'confirmationScope': 'built-in-chat',
                    'pendingConfirmation': ({'tool': s.pending_confirmation['tool'], 'summary': s.pending_confirmation['summary'],
                                              'details':s.pending_confirmation.get('details')} if s.pending_confirmation else None),
                    'lastResult': self.result_summary(s), 'lastError': s.error}

    def result_summary(self, s):
        if not s.result:
            return None
        from .chat_context import result_summary
        return result_summary(s.result['report'])

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
                       proposedBoundaryConditions=proposed_conditions(self, s), gravityLoads=self.gravity(s),
                       fluidDomainView=bool(self.workspace.get(s.model_id).get('domainGeneration')),
                       domainFaceRoles=(self.workspace.get(s.model_id).get('domainGeneration') or {}).get('faceRoles'))

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
        if tool == 'create_fluid_domain':
            return self.create_domain(sid,args)
        if tool in ('capture_viewport', 'pick_viewport_face'):
            return self.visual.request(sid, tool, args)
        if tool in ('recover_mechanical_run', 'recover_fluent_run'):
            return self.recover_code(sid, args)
        if tool == 'run_mechanical_code':
            return self.execute_code(sid, args)
        if tool == 'run_fluent_code':
            return self.execute_code(sid, args, solver='fluent')
        if tool == 'render_fluent_results':
            from fluent.postprocessing import render_result
            with self.lock:
                s, _ = self._checked(sid,args['model_id'],args['revision'])
                if any(a['status'] == 'unknown' for a in s.program_attempts) or not s.result:
                    raise ValueError('Recover the current job first; a completed Fluent result is required.')
                result = s.result
                s.running = True
            try:
                rendered = render_result(result)
                with self.lock:
                    s.result = rendered
                    s.revision += 1
                return {'result':self.result_summary(s), 'artifactsReady':True}
            finally:
                with self.lock:
                    s.running = False
        if tool == 'read_context':
            return self.context(sid)
        if tool == 'review_fluent_workflow':
            from fluent.workflow import review
            with self.lock:
                _, project = self._checked(sid,args['model_id'],args['revision'])
                return review(project)
        if tool in ('find_fluent_api','get_fluent_api_help','validate_fluent_api_code',
                    'validate_fluent_program','check_fluent_worker'):
            with self.lock:
                self._checked(sid,args.pop('model_id'),args.pop('revision'))
            # Never hold the session lock across MCP or worker network calls.
            # None of these read-only paths adds an attempt or approves a solve.
            if tool == 'check_fluent_worker':
                from .remote import check_fluent_worker
                return check_fluent_worker()
            if tool == 'validate_fluent_program':
                from fluent.contract import validate_program
                digest=validate_program(dict(title='Code validation',objective='Read-only worker-contract validation',**args))
                return {'valid':True,'programSHA256':digest,'validationScope':'worker-contract',
                        'solverLaunched':False,'liveAPIValidated':False}
            from fluent.mcp_tools import call_mcp
            upstream={'find_fluent_api':'find_api','get_fluent_api_help':'get_help',
                      'validate_fluent_api_code':'validate_code'}[tool]
            return call_mcp(upstream,args)
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
            elif tool == 'suggest_fluid_domain':
                return self.workspace.suggest_fluid_domain(model_id,**args)
            elif tool == 'set_simulation_intent':
                self.workspace.set_simulation_intent(model_id, **args)
                s.awaiting_simulation_choice = False
                s.pending_confirmation = None
                s.result, s.error = None, None
            elif tool == 'set_fluid_domain':
                self.workspace.set_fluid_domain(model_id, **args)
                s.awaiting_simulation_choice = False
                s.result, s.error = None, None
            elif tool == 'set_fluent_analysis':
                self.workspace.set_fluent_analysis(model_id, args)
                s.result, s.error = None, None
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
                from fluent.contract import KINDS
                from .thermal import KINDS as THERMAL_KINDS
                family = lambda k: 'fluid' if k in KINDS else 'thermal' if k in THERMAL_KINDS else 'structural'
                same = [r for r in same if family(r['type']) == family(kind)]
                record_id = args.get('record_id')
                if record_id is None and any(r['type'] == kind for r in same):
                    raise ValueError('This face already has that condition type. Pass its record_id to update it instead of adding it twice.')
                if kind in KINDS and any(r['id'] != record_id for r in same):
                    raise ValueError('A fluid face can have only one Fluent boundary condition. Edit or remove the existing one.')
                if kind in THERMAL_KINDS and any(r['id'] != record_id and (kind in ('temperature','adiabatic') or r['type'] in ('temperature','adiabatic')) for r in same):
                    raise ValueError('Prescribed temperature or insulation conflicts with another thermal condition on this face. Edit or remove it explicitly.')
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
            if tool in ('apply_condition', 'remove_condition', 'add_comment', 'set_fluent_analysis', 'set_simulation_intent', 'set_fluid_domain'):
                for other in self.sessions.values():
                    if other.id != sid and other.model_id == model_id:
                        other.revision += 1
                        if tool in ('apply_condition', 'remove_condition', 'set_fluent_analysis', 'set_simulation_intent', 'set_fluid_domain'):
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
                if getattr(exc,'submission_state',None) == 'not_submitted':
                    s.last_fingerprint = None
            raise
        finally:
            with self.lock:
                s.running = False
                s.revision += 1

    def create_domain(self,sid,args):
        """Build without blocking state polling; never alter or relabel source faces."""
        with self.lock:
            s,project = self._checked(sid,args['model_id'],args['revision'])
            if s.exporting or any(a['status'] == 'unknown' for a in s.program_attempts):
                raise ValueError('Finish/recover the current operation before preparing a new model.')
            definition = project.get('fluidDomain')
            if not definition:
                raise ValueError('Define the enclosure and CAD role first.')
            if definition.get('kind') == 'existing':
                if project.get('domainGeneration'):
                    return {'alreadyCreated':True,'context':self.context(sid)}
                raise ValueError('This CAD is already marked as fluid volume; no enclosure construction is needed.')
            model_id = s.model_id
            s.running,s.domain_building = True,True
            s.revision += 1
        try:
            derived = self.workspace.create_fluid_domain(model_id,definition)
            with self.lock:
                if s.model_id != model_id:
                    raise ValueError('The active CAD changed during construction; generated model remains saved but was not activated.')
                s.model_id = derived['id']
                s.selected,s.focus_face = None,None
                s.highlighted,s.gravity_loads = [],[]
                s.focus_token += 1
                s.result,s.mechanical_export,s.error = None,None,None
                s.material,s.small_deformation,s.element_size_mm = None,None,3.0
                s.last_fingerprint = None
                s.pending_confirmation,s.visual_frame,s.selection_event = None,None,None
                s.question = None
                s.awaiting_selection,s.awaiting_simulation_choice = False,False
                s.revision += 1
                self.add_message(sid,'assistant','Fluid geometry created. What next?',details=(
                    f'One watertight fluid region; volume {derived["domainGeneration"]["fluidVolumeMm3"]:.6g} mm³. '
                    'Original CAD retained. Boundary conditions were not copied to the new geometry. '
                    'Positive geometric clearance does not establish CFD domain-size independence.'),choices=[
                    {'label':'Set inlet and outlet','value':'Help me select inlet, outlet and wall conditions on the new fluid domain.'},
                    {'label':'Review geometry','value':'Show the fluid geometry checks and explain the remaining assumptions.'}])
                return {'created':True,'context':self.context(sid),'geometry':derived['domainGeneration']}
        except Exception as exc:
            with self.lock:
                s.error = str(exc)
            raise
        finally:
            with self.lock:
                s.running,s.domain_building = False,False
                s.revision += 1


    def execute_code(self, sid, args, solver='mechanical'):
        from mechanical.program import validate_program
        if solver == 'fluent':
            from fluent.contract import validate_program
        from mechanical.gravity import preview_gravity
        program = {key: args[key] for key in ('title', 'objective', 'code')}
        digest = validate_program(program)
        with self.lock:
            s, project = self._checked(sid, args['model_id'], args['revision'])
            # Retain failed preflight history for audit, but never use a definite
            # non-submission as evidence that the same code already executed.
            for old in s.program_attempts:
                if definite_non_submission(old):
                    old.update(status='not_submitted',submissionState='not_submitted',retryable=True,recoverable=False)
            if any(a['status'] == 'unknown' for a in s.program_attempts):
                raise ValueError('A previous program has uncertain execution status. Recover that job before submitting new code.')
            selected_face = s.selected
            fingerprint = hashlib.sha256(json.dumps({'modelId': s.model_id, 'code': digest, 'solver': solver,
                           'fluentAnalysis': project.get('fluentAnalysis') if solver == 'fluent' else None,
                           'simulationIntent': project.get('simulationIntent'), 'fluidDomain': project.get('fluidDomain'),
                           'conditions': project['boundaryConditions'], 'selectedFace': selected_face}, sort_keys=True).encode()).hexdigest()
            previous = next((a for a in reversed(s.program_attempts)
                             if a['fingerprint'] == fingerprint and not definite_non_submission(a)), None)
            if previous:
                if previous.get('report'):
                    if previous.get('result'):
                        s.result = previous['result']
                        s.error = previous['report'].get('error')
                        s.gravity_loads = [dict(row, state='applied') for row in previous['report'].get('gravityLoads') or []] if previous['status'] == 'succeeded' else []
                        s.revision += 1
                    return {'alreadyRun': True, 'result': previous['report']}
                raise ValueError('This exact program was already submitted. Recover its existing job before running it again.')
            # Preflight errors are definite non-submissions, not uncertain remote jobs.
            if solver == 'fluent' and self.fluent_runner is run_remote_fluent_code:
                from .simulation import prepare_fluent_request
                prepare_fluent_request(self.workspace, s.model_id, program, selected_face)
            attempt = {'title': program['title'], 'solver': solver, 'programSHA256': digest, 'fingerprint': fingerprint,
                       'status': 'running','submissionState':'preparing','retryable':False}
            s.program_attempts.append(attempt)
            s.running, s.result, s.error = True, None, None
            s.gravity_loads = [dict(row, state='running') for row in preview_gravity(program['code'])] if solver == 'mechanical' else []
            latest_code = next((m['content'] for m in reversed(s.messages) if isinstance(m['content'], dict) and 'code' in m['content']), None)
            if not latest_code or latest_code['code'] != program['code']:
                s.messages.append({'role': 'assistant', 'content': {'code': program['code'], 'title': program['title']}})
            s.messages.append({'role': 'assistant', 'content': '**Preparing solver run:** ' + program['title']})
            s.revision += 1
            model_id = s.model_id
        try:
            runner = self.fluent_runner if solver == 'fluent' else self.code_runner
            result = runner(self.workspace, model_id, program, selected_face)
            if solver == 'fluent' and runner is run_remote_fluent_code:
                from fluent.postprocessing import enrich_result
                result = enrich_result(result)
            with self.lock:
                s.result = result
                s.error = result['report'].get('error')
                s.gravity_loads = [dict(row, state='applied') for row in result['report'].get('gravityLoads', [])] if result['report']['status'] == 'succeeded' else []
                attempt.update(status=result['report']['status'],submissionState='completed',retryable=False,
                               error=s.error,report=self.result_summary(s),result=result)
                return {'result': attempt['report'], 'artifactsReady': True}
        except Exception as exc:
            with self.lock:
                s.error = str(exc)
                s.gravity_loads = []
                not_submitted = getattr(exc,'submission_state',None) == 'not_submitted'
                attempt.update(status='not_submitted' if not_submitted else 'unknown',
                               submissionState='not_submitted' if not_submitted else 'unknown',retryable=not_submitted,
                               error=s.error,recordPath=getattr(exc,'record_path',None),
                               recoverable=not not_submitted and bool(getattr(exc,'record_path',None)))
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
            from fluent.postprocessing import enrich_result
            recovered_result = enrich_result(result_files(path.parent, report))
            with self.lock:
                s.result = recovered_result
                s.error = report.get('error')
                s.gravity_loads = [dict(row, state='applied') for row in report.get('gravityLoads', [])] if report['status'] == 'succeeded' else []
                attempt.update(status=report['status'],submissionState='completed',retryable=False,
                               error=s.error,report=self.result_summary(s),result=s.result,recoverable=False)
                return {'recovered': True, 'result': self.result_summary(s), 'artifactsReady': True}
        finally:
            with self.lock:
                s.running = False
                s.revision += 1
