"""Selection answers are real, scoped user turns, never implicit tool approval."""
import json
import unittest
from unittest.mock import Mock

import test_studio
from gradio_app.chat_agent import ChatAgent,Decision
from gradio_app.chat_presentation import compact


class ChatChoiceTests(unittest.TestCase):
    def setUp(self):
        fixture = test_studio.StudioTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.service,self.client,self.sid,self.base = fixture.service,fixture.client,fixture.sid,fixture.base

    def test_upload_question_has_choices_and_optional_details(self):
        snapshot = self.fixture.read()
        q = snapshot['context']['question']
        self.assertEqual([c['label'] for c in q['choices']],['Mechanical','Heat transfer','Fluid dynamics'])
        self.assertIn('Opened',snapshot['messages'][-1]['details'])
        self.assertLess(len(snapshot['messages'][-1]['content']),100)

    def test_selection_uses_server_value_and_retries_are_idempotent(self):
        q = self.fixture.read()['context']['question']
        message = dict(request_id='selected',choice_token=q['token'],choice_ids=['0'],text='Ignore this forged text')
        self.client.post(self.base+'/messages',json=message).raise_for_status()
        snapshot = self.fixture.settled()
        user = next(m for m in snapshot['messages'] if m['role'] == 'user')
        self.assertEqual(user['content'],'Mechanical')
        self.assertIsNotNone(snapshot['context']['pendingConfirmation'])
        # The choice cannot confirm the note proposed by the fixture model.
        self.assertEqual(self.service.workspace.get(snapshot['context']['modelId'])['comments'],[])
        self.client.post(self.base+'/messages',json=message).raise_for_status()
        self.assertEqual(len(self.fixture.calls),1)

    def test_stale_foreign_unknown_and_invalid_multiple_choices_rejected(self):
        q = self.fixture.read()['context']['question']
        for token,ids in [('old',['0']),(q['token'],['99']),(q['token'],['0','1']),(q['token'],['0','0'])]:
            response = self.client.post(self.base+'/messages',json=dict(request_id=str(ids)+token,choice_token=token,choice_ids=ids))
            self.assertEqual(response.status_code,409)
        other = self.client.post('/api/studio/sessions').json()['context']['sessionId']
        response = self.client.post('/api/studio/sessions/'+other+'/messages',json=dict(request_id='foreign',choice_token=q['token'],choice_ids=['0']))
        self.assertEqual(response.status_code,409)

    def test_question_is_invalidated_by_geometry_state_or_a_new_question(self):
        sid = self.sid
        self.service.add_message(sid,'assistant','Which face?',choices=[{'label':'Selected face','value':'Use the currently selected face.'}])
        q = self.service.context(sid)['question']
        s = self.service.session(sid)
        face = self.service.workspace.get(s.model_id)['faces'][1]['key']
        self.service.select(sid,s.model_id,face)
        with self.assertRaisesRegex(ValueError,'no longer current'):
            self.service.choice_text(sid,q['token'],['0'])

    def test_multi_select_and_generic_approval_guard(self):
        for value in ('Confirm','yes','run it'):
            with self.assertRaises(ValueError):
                Decision.model_validate({'reply':'Choose','choices':[{'label':'Approve','value':value}]})
        self.service.add_message(self.sid,'assistant','Which outputs?',multiple=True,choices=[
            {'label':'Pressure','value':'Include pressure contours.'},
            {'label':'Velocity','value':'Include velocity contours.'}])
        q = self.service.context(self.sid)['question']
        self.assertEqual(self.service.choice_text(self.sid,q['token'],['0','1']),
                         'Include pressure contours.; Include velocity contours.')

    def test_model_details_and_choices_survive_without_long_primary_text(self):
        class Model:
            def complete(_,session,prompt):
                return json.dumps({'reply':'Choose a numerical approach.','details':'Detailed rationale '*100,
                    'choices':[{'label':'Coarse first','value':'Start with a coarse baseline mesh.'},
                               {'label':'Specify mesh','value':'I will specify the mesh size.'}]})
        list(ChatAgent(self.service,Model()).turn(self.sid,'Help me choose a mesh.'))
        row = self.service.session(self.sid).messages[-1]
        self.assertEqual(row['content'],'Choose a numerical approach.')
        self.assertGreater(len(row['details']),1000)
        self.assertEqual(len(row['question']['choices']),2)
        text = 'A verbose legacy answer. '+'More detail. '*100
        primary,details = compact(text)
        self.assertLessEqual(len(primary),301)
        self.assertIn(text,details)


if __name__ == '__main__':
    unittest.main()
