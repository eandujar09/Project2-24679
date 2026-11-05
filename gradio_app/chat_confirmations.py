"""Chat-only confirmation gates: the model can propose actions, never approve them."""
import hashlib
import json
import re

from .chat_tools import ARGUMENT_MODELS
from .backend import finite

GUARDED_TOOLS = frozenset({'set_analysis', 'apply_condition', 'remove_condition', 'add_comment',
                           'run_simulation', 'run_mechanical_code'})
AFFIRMATIONS = frozenset({'yes', 'yep', 'yeah', 'correct', 'confirmed', 'confirm', 'i confirm',
                         'yes confirm', 'yes please', 'yes that is correct', 'yes thats correct',
                         'thats correct', 'that is correct', 'thats right', 'that is right',
                         'yes go ahead', 'go ahead', 'proceed', 'apply it', 'yes apply it',
                         'run it', 'yes run it', 'approve', 'i approve', 'ok', 'okay'})


def is_confirmation(text):
    # Extra values, qualifications, negatives or instructions need a revised proposal.
    if '?' in text:
        return False
    normalized = re.sub(r'[^a-z0-9\s]', '', text.lower())
    return ' '.join(normalized.split()) in AFFIRMATIONS


def state_fingerprint(service, session):
    project = service.workspace.get(session.model_id)
    state = {'modelId': session.model_id, 'selected': session.selected,
             'highlighted': session.highlighted, 'conditions': project['boundaryConditions'],
             'comments': project['comments'], 'material': session.material,
             'smallDeformation': session.small_deformation, 'meshSize': session.element_size_mm}
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


def propose(service, sid, tool, arguments, explanation):
    args = ARGUMENT_MODELS[tool].model_validate(arguments).model_dump(exclude_none=True)
    if tool == 'apply_condition':
        kind, values = args['kind'], args['values']
        if kind in ('force', 'displacement') and not all(finite(values.get(axis)) for axis in 'xyz'):
            raise ValueError('Specify finite X, Y and Z components before proposing this condition.')
        if kind == 'force' and not any(values[axis] for axis in 'xyz'):
            raise ValueError('Force must have a nonzero resultant.')
        if kind == 'pressure' and (not finite(values.get('magnitude')) or values['magnitude'] == 0):
            raise ValueError('Specify a finite nonzero pressure before proposing it.')
    if tool == 'run_mechanical_code':
        from mechanical.program import validate_program
        validate_program(args)
    with service.lock:
        session, project = service._checked(sid, args['model_id'], args['revision'])
        key = args.get('face_key')
        record = None
        if tool == 'remove_condition':
            record = next((r for r in project['boundaryConditions'] if r['id'] == args['record_id']), None)
            if record is None:
                raise ValueError('That condition is no longer in this model.')
            key = record['faceKey']
        if key:
            service.workspace.require_face(project, key)
            session.highlighted = [key]
            session.focus_face = key
            session.focus_token += 1
        face = next((f for f in project['faces'] if f['key'] == key), None)
        label = f'Face {face["index"]} (highlighted in violet)' if face else 'the current model'
        if tool == 'apply_condition':
            kind, values = args['kind'], args['values']
            if kind == 'fixed':
                change = f'Fully fix **{label}**: X, Y and Z translation = 0.'
            elif kind == 'pressure':
                change = f'Apply **{values.get("magnitude")} MPa pressure** on **{label}** (positive = inward, negative = outward).'
            else:
                unit = 'N' if kind == 'force' else 'mm'
                vector = ', '.join(f'{axis.upper()} = {values.get(axis)} {unit}' for axis in 'xyz')
                description = 'total force' if kind == 'force' else 'displacement'
                change = f'Apply **{description}** on **{label}**, in global coordinates: **{vector}**.'
        elif tool == 'set_analysis':
            change = f'Use **{args["material"]}**, linear static small deformation, with a **{args["element_size_mm"]} mm** mesh setting.'
        elif tool == 'remove_condition':
            change = f'Remove the **{record["type"]}** condition from **{label}**.'
        elif tool == 'add_comment':
            change = f'Add this note to **{label}**: “{args["text"]}”'
        elif tool == 'run_mechanical_code':
            change = f'Execute the proposed Python for **{args["title"]}**.\n\n{args["objective"]}'
            service.add_message(sid, 'assistant', {'code': args['code'], 'title': 'Proposed Python · ' + args['title']})
        else:
            change = 'Run the current saved simulation setup in Ansys.'
        summary = '**Please confirm this proposal.**\n\n'
        if explanation.strip():
            summary += explanation.strip() + '\n\n'
        summary += change + '\n\n'
        summary += ('Are the setup, highlighted faces, and planned run correct? ' if tool in ('run_simulation', 'run_mechanical_code')
                    else 'Is this the setup you intended? ' if tool == 'set_analysis'
                    else 'Is that the face and interpretation you intended? ')
        summary += 'Reply **Confirm** to proceed, or tell me what to change. Nothing has been applied or run from this proposal.'
        session.pending_confirmation = {'tool': tool, 'arguments': args, 'summary': change,
                                        'fingerprint': state_fingerprint(service, session)}
        session.awaiting_selection = False
        service.add_message(sid, 'assistant', summary)
        return session.pending_confirmation


def consume_confirmation(service, sid, text):
    """Called only on a new real user turn, never on a model/tool response."""
    with service.lock:
        session = service.session(sid)
        pending = session.pending_confirmation
        if pending is None:
            return None
        if not is_confirmation(text):
            # A correction or question is not approval; let the model explain/revise.
            session.pending_confirmation = None
            return None
        session.pending_confirmation = None
        if pending['fingerprint'] != state_fingerprint(service, session):
            service.add_message(sid, 'assistant', 'The selection or setup changed since that proposal. I’ll review it with you again before applying anything.')
            return None
        args = dict(pending['arguments'], revision=session.revision)
        return {'tool': pending['tool'], 'arguments': args}
