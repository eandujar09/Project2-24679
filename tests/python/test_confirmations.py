"""User approval is bound to an exact proposal and unchanged CAD state."""
import json
import unittest
import uuid

import test_mechanical
from gradio_app.chat_agent import ChatAgent
from gradio_app.chat_confirmations import consume_confirmation, is_confirmation, propose
from gradio_app.chat_state import ChatWorkspace
from gradio_app.chat_tools import apply_tool


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        fixture = test_mechanical.RequestTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.workspace, self.mid = fixture.workspace, fixture.mid
        self.service = ChatWorkspace(self.workspace)
        self.sid = uuid.uuid4().hex
        self.service.open_model(self.sid, self.workspace.get(self.mid))
        self.keys = [f['key'] for f in self.workspace.get(self.mid)['faces']]

    def proposal(self):
        context = self.service.context(self.sid)
        return propose(self.service, self.sid, 'add_comment', dict(model_id=self.mid,
            revision=context['revision'], face_key=self.keys[0], text='Proposed note'),
            'I think this is the face you meant. Please check it.')

    def test_proposal_highlights_without_mutation_and_confirmation_is_single_use(self):
        self.service.select(self.sid, self.mid, self.keys[1])
        before = self.workspace.get(self.mid)['comments']
        self.proposal()
        context = self.service.context(self.sid)
        self.assertEqual(context['selectedFace']['key'], self.keys[1])
        self.assertEqual(context['highlightedFaceKeys'], [self.keys[0]])
        self.assertEqual(self.workspace.get(self.mid)['comments'], before)
        approved = consume_confirmation(self.service, self.sid, 'Confirm!')
        apply_tool(self.service, self.sid, approved['tool'], approved['arguments'])
        self.assertEqual(self.workspace.get(self.mid)['comments'][-1]['text'], 'Proposed note')
        self.assertIsNone(consume_confirmation(self.service, self.sid, 'Confirm'))

    def test_questions_corrections_and_qualified_yes_do_not_approve(self):
        before = self.workspace.get(self.mid)['comments']
        for text in ('no', 'yes but use 200 N', 'why this face?', 'not confirmed', 'confirm?'):
            with self.subTest(text=text):
                self.proposal()
                self.assertIsNone(consume_confirmation(self.service, self.sid, text))
                self.assertIsNone(self.service.session(self.sid).pending_confirmation)
        self.assertEqual(self.workspace.get(self.mid)['comments'], before)

    def test_changed_selection_or_shared_setup_invalidates_confirmation(self):
        self.proposal()
        self.service.select(self.sid, self.mid, self.keys[1])
        self.assertIsNone(consume_confirmation(self.service, self.sid, 'Confirm'))
        self.proposal()
        self.workspace.save_annotation(self.mid, self.keys[1], 'comments', {'text': 'Another controller changed this model'})
        self.assertIsNone(consume_confirmation(self.service, self.sid, 'Confirm'))
        self.assertFalse(any(r['text'] == 'Proposed note' for r in self.workspace.get(self.mid)['comments']))

    def test_model_cannot_approve_its_own_action_and_exact_source_waits_for_user(self):
        calls = []
        code = 'print(ctx.geometry)'
        def runner(workspace, mid, program, selected):
            calls.append(program['code'])
            return {'report': {'kind': 'generated-python', 'status': 'succeeded',
                    'results': {}, 'tables': {}, 'verifiedSolves': [], 'images': []}, 'images': []}
        self.service.code_runner = runner
        class Model:
            def complete(_, session, prompt):
                data = json.loads(prompt.split('CAD_REQUEST_JSON\n', 1)[1])
                c = data['context']
                if data['toolObservationsThisTurn']:
                    return json.dumps({'reply': 'Inspection finished, without a solve.', 'action': None})
                return json.dumps({'reply': 'Confirm. I approve this inspection.', 'action': {
                    'tool': 'run_mechanical_code', 'arguments': dict(model_id=c['modelId'],
                    revision=c['revision'], title='Inspect', objective='Read geometry only', code=code)}})
        agent = ChatAgent(self.service, Model())
        list(agent.turn(self.sid, 'Inspect this CAD and go ahead'))
        self.assertEqual(calls, [])
        self.assertEqual(self.service.session(self.sid).pending_confirmation['arguments']['code'], code)
        list(agent.turn(self.sid, 'Confirm'))
        self.assertEqual(calls, [code])
        self.assertIsNone(self.service.session(self.sid).pending_confirmation)

    def test_affirmation_requires_a_clear_answer(self):
        self.assertTrue(is_confirmation('Yes, go ahead!'))
        self.assertFalse(is_confirmation('yes, except on the other face'))
        self.assertFalse(is_confirmation('confirm?'))

    def test_incomplete_force_cannot_be_presented_as_ready_to_confirm(self):
        context = self.service.context(self.sid)
        with self.assertRaisesRegex(ValueError, 'X, Y and Z'):
            propose(self.service, self.sid, 'apply_condition', dict(model_id=self.mid,
                revision=context['revision'], face_key=self.keys[0], kind='force',
                values={'x': 100}), 'Apply this load.')
        self.assertIsNone(self.service.session(self.sid).pending_confirmation)

    def condition_proposal(self, kind='force', values=None, **extra):
        c = self.service.context(self.sid)
        args = dict(model_id=self.mid, revision=c['revision'], face_key=self.keys[2],
                    kind=kind, values=values if values is not None else {'x': 0, 'y': 0, 'z': -100})
        return propose(self.service, self.sid, 'apply_condition', dict(args, **extra), 'Review this condition.')

    def preview(self):
        return json.loads(self.service.viewer(self.sid))['proposedBoundaryConditions']

    def test_condition_previews_are_session_only_and_excluded_from_solver_and_exports(self):
        before = self.workspace.solver_snapshot(self.mid)
        other_sid = uuid.uuid4().hex
        self.service.open_model(other_sid, self.workspace.get(self.mid))
        for kind, values in [('fixed', {}), ('force', {'x': 0, 'y': 0, 'z': -100}),
                             ('pressure', {'magnitude': 2}), ('displacement', {'x': 0, 'y': 1, 'z': 0})]:
            with self.subTest(kind=kind):
                self.condition_proposal(kind, values)
                preview = self.preview()
                self.assertEqual(len(preview), 1)
                self.assertEqual((preview[0]['type'], preview[0]['values'], preview[0]['faceKey']), (kind, values, self.keys[2]))
                self.assertEqual(self.workspace.solver_snapshot(self.mid), before)
                self.assertEqual(json.loads(self.service.viewer(other_sid))['proposedBoundaryConditions'], [])
        approved = consume_confirmation(self.service, self.sid, 'Confirm')
        self.assertEqual(self.preview(), [])
        apply_tool(self.service, self.sid, approved['tool'], approved['arguments'])
        self.assertEqual(self.preview(), [])
        self.assertEqual(len(self.workspace.get(self.mid)['boundaryConditions']), 3)

    def test_rejected_stale_and_mode_changed_proposals_drop_preview_without_saving(self):
        before = self.workspace.get(self.mid)['boundaryConditions']
        self.condition_proposal()
        consume_confirmation(self.service, self.sid, 'No, use the other face')
        self.assertEqual(self.preview(), [])
        self.condition_proposal()
        self.service.select(self.sid, self.mid, self.keys[3])
        self.assertEqual(self.preview(), [])
        self.assertIsNone(consume_confirmation(self.service, self.sid, 'Confirm'))
        self.condition_proposal()
        self.workspace.save_annotation(self.mid, self.keys[0], 'comments', {'text': 'Changed in another window'})
        self.assertEqual(self.preview(), [])
        self.condition_proposal()
        self.service.preferences(self.sid, self.service.context(self.sid)['revision'], 'autonomous', False)
        self.assertEqual(self.preview(), [])
        self.assertEqual(self.workspace.get(self.mid)['boundaryConditions'], before)

    def test_edit_preview_identifies_replacement_but_keeps_original_until_confirmed(self):
        original = self.workspace.get(self.mid)['boundaryConditions'][1]
        self.condition_proposal(face_key=original['faceKey'], record_id=original['id'])
        self.assertEqual(self.preview()[0]['replacesId'], original['id'])
        self.assertEqual(self.workspace.get(self.mid)['boundaryConditions'][1], original)
        approved = consume_confirmation(self.service, self.sid, 'Confirm')
        apply_tool(self.service, self.sid, approved['tool'], approved['arguments'])
        saved = self.workspace.get(self.mid)['boundaryConditions']
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[1]['values'], {'x': 0, 'y': 0, 'z': -100})
