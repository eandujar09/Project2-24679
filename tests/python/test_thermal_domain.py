"""Heat-transfer glyph state and user-defined CFD onboarding; no licensed solve."""
import json
import unittest
import uuid
from unittest.mock import Mock

import test_mechanical
from gradio_app.chat_state import ChatWorkspace
from gradio_app.chat_agent import ChatAgent
from gradio_app.chat_tools import apply_tool
from gradio_app.chat_confirmations import propose, proposed_conditions, consume_confirmation
from gradio_app.thermal import condition_values
from gradio_app.fluid_domain import validate_domain
from gradio_app.simulation import prepare_code_request, prepare_request, prepare_fluent_request


class ThermalDomainTests(unittest.TestCase):
    def setUp(self):
        fixture = test_mechanical.RequestTests(); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.workspace, self.mid = fixture.workspace, fixture.mid
        self.service = ChatWorkspace(self.workspace)
        self.sid = uuid.uuid4().hex
        self.service.open_model(self.sid,self.workspace.get(self.mid))
        self.face = self.workspace.get(self.mid)['faces'][0]['key']

    def args(self, **values):
        return dict(model_id=self.mid,revision=self.service.context(self.sid)['revision'],**values)

    def test_opened_cad_asks_three_way_question_and_does_not_ask_for_a_face(self):
        message = self.service.session(self.sid).messages[-1]['content']
        for choice in ('mechanical','heat transfer','fluid dynamics'):
            self.assertIn(choice,message)
        self.assertFalse(self.service.session(self.sid).awaiting_selection)
        fresh = self.workspace.open_step(self.workspace.root/'models'/f'{self.mid}.step',fresh=True)
        self.service.open_model(self.sid,fresh)
        self.assertIsNone(self.service.context(self.sid)['simulationIntent'])

    def test_fluid_choice_asks_about_existing_box_pipe_or_other_domain_in_both_modes(self):
        for mode in ('guided','autonomous'):
            self.service.session(self.sid).interaction_mode = mode
            class Model:
                def complete(_,session,prompt):
                    c = json.loads(prompt.split('CAD_REQUEST_JSON\n')[1])['context']
                    return json.dumps({'reply':'You selected fluid dynamics.', 'action':{'tool':'set_simulation_intent',
                        'arguments':dict(model_id=c['modelId'],revision=c['revision'],simulation_type='fluid')}})
            list(ChatAgent(self.service,Model()).turn(self.sid,'Fluid dynamics'))
            last = self.service.session(self.sid).messages[-1]
            message = last['content']+' '+last.get('details','')
            for text in ('fluid domain','box','cylindrical/pipe','another standard technique'):
                self.assertIn(text,message)
            self.assertEqual(self.service.context(self.sid)['simulationIntent']['type'],'fluid')

    def test_thermal_units_validate_before_preview_or_persistence(self):
        for kind,values in [('temperature',{'temperature':-274}),('radiation',{'emissivity':1.1,'ambient_temperature':20}),
                            ('convection',{'coefficient':0,'ambient_temperature':20}),('heat_flux',{'magnitude':float('nan')}),
                            ('adiabatic',{'x':1}),('temperature',{'temperature':True})]:
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                propose(self.service,self.sid,'apply_condition',self.args(face_key=self.face,kind=kind,values=values),'Preview')
        self.assertIsNone(self.service.session(self.sid).pending_confirmation)
        self.assertEqual(condition_values('heat_flux',{'magnitude':0}),{'magnitude':0})

    def test_all_thermal_conditions_preview_save_and_round_trip(self):
        faces = self.workspace.get(self.mid)['faces']
        kinds = [('temperature',{'temperature':80}),('heat_flux',{'magnitude':-500}),
                 ('convection',{'coefficient':15,'ambient_temperature':25}),
                 ('radiation',{'emissivity':0.8,'ambient_temperature':20}),('adiabatic',{})]
        for face,(kind,values) in zip(faces,kinds):
            propose(self.service,self.sid,'apply_condition',self.args(face_key=face['key'],kind=kind,values=values),'Thermal preview')
            self.assertEqual(proposed_conditions(self.service,self.service.session(self.sid))[0]['type'],kind)
            confirmed = consume_confirmation(self.service,self.sid,'Confirm')
            apply_tool(self.service,self.sid,confirmed['tool'],confirmed['arguments'])
        portable = self.workspace.export_annotations(self.mid)
        project = self.workspace.import_annotations(self.mid,portable)
        self.assertTrue({k for k,v in kinds}.issubset({r['type'] for r in project['boundaryConditions']}))

    def test_thermal_conflicts_do_not_treat_structural_support_as_insulation(self):
        apply_tool(self.service,self.sid,'apply_condition',self.args(face_key=self.face,kind='temperature',values={'temperature':80}))
        with self.assertRaisesRegex(ValueError,'thermal condition'):
            apply_tool(self.service,self.sid,'apply_condition',self.args(face_key=self.face,kind='adiabatic',values={}))
        rows = self.workspace.get(self.mid)['boundaryConditions']
        self.assertIn('temperature',{r['type'] for r in rows})
        self.assertIn('fixed',{r['type'] for r in rows})

    def test_heat_transfer_routes_saved_conditions_only_to_generated_thermal_setup(self):
        apply_tool(self.service,self.sid,'apply_condition',self.args(face_key=self.face,kind='temperature',values={'temperature':80}))
        apply_tool(self.service,self.sid,'set_simulation_intent',self.args(simulation_type='heat_transfer'))
        request = prepare_code_request(self.workspace,self.mid,{'title':'Thermal inspection','objective':'Inspect','code':'print(ctx.conditions)'})
        self.assertEqual({r['type'] for r in request['boundaryConditions']},{'temperature'})
        self.assertNotIn('temperature',{r['type'] for r in prepare_request(self.workspace,self.mid)['boundaryConditions']})

    def test_box_pipe_and_custom_definitions_are_validated_not_fabricated_geometry(self):
        box = dict(min_x=-10,min_y=-10,min_z=-10,max_x=100,max_y=30,max_z=30)
        pipe = dict(origin_x=0,origin_y=0,origin_z=0,axis_x=1,axis_y=0,axis_z=0,radius=15,length=100)
        for kind,role,params in [('box','obstacle',box),('cylinder','reference',pipe),('custom','reference',{'inner_radius':5,'outer_radius':10})]:
            args = self.args(kind=kind,cad_role=role,parameters=params,description='User specified an internal/external flow domain.')
            propose(self.service,self.sid,'set_fluid_domain',args,'Record the chosen domain.')
            confirmed = consume_confirmation(self.service,self.sid,'Confirm')
            apply_tool(self.service,self.sid,confirmed['tool'],confirmed['arguments'])
            domain = self.service.context(self.sid)['fluidDomain']
            self.assertEqual(domain['kind'],kind)
            self.assertEqual(domain['status'],'needs_preparation')
            with self.assertRaisesRegex(ValueError,'prepare the actual fluid volume'):
                prepare_fluent_request(self.workspace,self.mid,{'title':'Flow','objective':'Test','code':'ctx.solve()'})
        self.assertEqual(self.workspace.get(self.mid)['fluidDomain']['parameters'],{'inner_radius':5,'outer_radius':10})
        with self.assertRaises(ValueError):
            validate_domain('box','obstacle',dict(box,max_x=-20),'Invalid extents')
        with self.assertRaises(ValueError):
            validate_domain('cylinder','reference',dict(pipe,axis_x=0),'Zero axis')
        with self.assertRaises(ValueError):
            validate_domain('existing','obstacle',{},'Not the actual fluid volume')

    def test_changing_intent_invalidates_thermal_proposal_and_preserves_user_domain(self):
        propose(self.service,self.sid,'apply_condition',self.args(face_key=self.face,kind='temperature',values={'temperature':80}),'Preview')
        apply_tool(self.service,self.sid,'set_simulation_intent',self.args(simulation_type='fluid'))
        self.assertIsNone(self.service.session(self.sid).pending_confirmation)
        self.assertEqual(proposed_conditions(self.service,self.service.session(self.sid)),[])


if __name__ == '__main__':
    unittest.main()
