"""Optional browser-rendered screenshots and picks scoped to their frozen camera."""
import base64
import io
from threading import Event
import uuid

from PIL import Image


class VisualBridge:
    def __init__(self, service):
        self.service = service
        self.pending = {}
        self.timeout = 20

    def fingerprint(self, session):
        from .chat_confirmations import state_fingerprint
        return state_fingerprint(self.service, session)

    def frame(self, session):
        frame = session.visual_frame
        if (not session.visual_enabled or not frame or frame['modelId'] != session.model_id
                or frame['fingerprint'] != self.fingerprint(session)):
            return None
        return frame

    def context(self, session):
        frame = self.frame(session)
        pending = self.pending.get(session.id)
        return {'enabled': session.visual_enabled,
                'frame': {k: frame[k] for k in ('id', 'width', 'height', 'view')} if frame else None,
                'request': pending['public'] if pending and not pending['event'].is_set() else None}

    def request(self, sid, tool, args):
        with self.service.lock:
            session, _ = self.service._checked(sid, args['model_id'], args['revision'])
            if not session.visual_enabled:
                raise ValueError('Visual assistance is off. The user can enable it in the composer.')
            if sid in self.pending:
                raise ValueError('A viewport request is already pending.')
            frame = self.frame(session)
            if tool == 'pick_viewport_face':
                if not frame or frame['id'] != args['frame_id']:
                    raise ValueError('That screenshot is stale. Capture the viewport again.')
                if not 0 <= args['x'] < frame['width'] or not 0 <= args['y'] < frame['height']:
                    raise ValueError('The point is outside the screenshot. Use image pixels from its top-left corner.')
            else:
                session.visual_frame = None
            public = {'id': uuid.uuid4().hex, 'tool': tool, 'modelId': session.model_id,
                      **{k: v for k, v in args.items() if k not in ('model_id', 'revision')}}
            pending = {'public': public, 'event': Event(), 'fingerprint': self.fingerprint(session)}
            self.pending[sid] = pending
            session.revision += 1
        try:
            if not pending['event'].wait(self.timeout):
                raise ValueError('The viewport did not respond. Keep the CAD browser tab open, or continue using geometry data.')
            if pending.get('error'):
                raise ValueError(pending['error'])
            return pending['result']
        finally:
            with self.service.lock:
                self.pending.pop(sid, None)
                session.revision += 1

    def respond(self, sid, request_id, body):
        with self.service.lock:
            session = self.service.existing(sid)
            pending = self.pending.get(sid)
            if not pending or pending['public']['id'] != request_id or pending['event'].is_set():
                raise ValueError('This viewport request has expired or was already answered.')
            public = pending['public']
            try:
                if (not session.visual_enabled or body['model_id'] != session.model_id
                        or public['modelId'] != session.model_id
                        or pending['fingerprint'] != self.fingerprint(session)):
                    raise ValueError('The CAD state changed while capturing the viewport. Capture it again.')
                if body.get('error'):
                    raise ValueError(body['error'])
                if public['tool'] == 'capture_viewport':
                    data = body.get('image', '')
                    if not data.startswith('data:image/png;base64,'):
                        raise ValueError('Return a PNG screenshot of the CAD viewport.')
                    raw = base64.b64decode(data.split(',', 1)[1], validate=True)
                    with Image.open(io.BytesIO(raw)) as image:
                        width, height = image.size
                        if image.format != 'PNG' or not (1 <= width <= 1600 and 1 <= height <= 1600):
                            raise ValueError('Screenshot dimensions must be between 1 and 1600 pixels.')
                        image.verify()
                    session.visual_frame = {'id': request_id, 'modelId': session.model_id,
                        'width': width, 'height': height, 'view': public.get('view', 'current'),
                        'image': data, 'fingerprint': self.fingerprint(session)}
                    pending['result'] = {'frameId': request_id, 'width': width, 'height': height,
                                         'view': public.get('view', 'current'), 'imageAttached': True}
                else:
                    key = body.get('face_key')
                    if key:
                        project = self.service.workspace.get(session.model_id)
                        self.service.workspace.require_face(project, key)
                        face = next(f for f in project['faces'] if f['key'] == key)
                        session.highlighted = [key]
                        pending['result'] = {'faceKey': key, 'faceIndex': face['index'],
                            'frameId': public['frame_id'], 'x': public['x'], 'y': public['y'],
                            'highlighted': True, 'userSelectionChanged': False}
                    else:
                        pending['result'] = {'faceKey': None, 'frameId': public['frame_id'],
                            'message': 'That pixel is background; no face was hit.'}
                session.revision += 1
            except (ValueError, OSError, Image.DecompressionBombError) as exc:
                pending['error'] = str(exc)
                raise ValueError(str(exc)) from exc
            finally:
                pending['event'].set()
