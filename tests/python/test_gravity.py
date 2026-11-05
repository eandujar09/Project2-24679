import json
from types import SimpleNamespace as Obj
import unittest
import uuid

import test_mechanical
from mechanical.gravity import G, acceleration, preview_gravity, read_gravity
from gradio_app.chat_state import ChatWorkspace
from gradio_app.chat_confirmations import propose, consume_confirmation

DOWN = 'g = analysis.AddEarthGravity()\ng.Direction = GravityOrientationType.NegativeZAxis\n'


class GravityTests(unittest.TestCase):
    def test_direction_and_historical_remote_component_conventions(self):
        self.assertEqual(preview_gravity(DOWN)[0]['vector'], [0, 0, -G])
        for component in (G, -G):
            code = "gravity = analysis.AddEarthGravity()\ngravity.DefineBy = LoadDefineBy.Components\n"
            code += '\n'.join(f"gravity.{a}Component.Output.DiscreteValues = [Quantity({v}, 'm s^-2')]" for a, v in zip('XYZ', [0, 0, component]))
            self.assertEqual(preview_gravity(code)[0]['vector'], [0, 0, -component])
        self.assertAlmostEqual(acceleration(9806.65, 'mm sec^-1 sec^-1'), G)

    def test_comments_disabled_deleted_and_uncertain_code(self):
        self.assertEqual(preview_gravity("# analysis.AddEarthGravity()\nprint('no gravity')"), [])
        self.assertEqual(preview_gravity(DOWN + 'g.Suppressed = True'), [])
        self.assertEqual(preview_gravity(DOWN + 'g.Delete()'), [])
        self.assertIsNone(preview_gravity('if enabled:\n    ' + DOWN.replace('\n', '\n    ').rstrip())[0]['vector'])
        self.assertIsNone(preview_gravity(DOWN + 'g.CoordinateSystem = local_cs')[0]['vector'])
        self.assertIsNone(preview_gravity(DOWN + 'g.ZComponent.Output.DiscreteValues = values')[0]['vector'])

    def test_actual_mechanical_readback_uses_units_suppression_and_global_frame(self):
        def load(z, suppressed=False, cs=18):
            return Obj(ObjectId=42, Suppressed=suppressed, CoordinateSystem=Obj(ObjectId=cs),
                       **{a + 'Component': Obj(Output=Obj(DiscreteValues=[Obj(Value=v, Unit='mm sec^-1 sec^-1')]))
                          for a, v in zip('XYZ', [0, 0, z])})
        model = Obj(CoordinateSystems=Obj(Children=[Obj(ObjectId=18)]), Analyses=[
            Obj(Name='Static', GetChildren=lambda *_: [load(9806.65), load(-9806.65), load(9806.65, True), load(9806.65, cs=99)])])
        rows = read_gravity({'Model': model, 'DataModelObjectCategory': Obj(EarthGravity='gravity')})
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['vector'], [0, 0, -G])
        self.assertEqual(rows[1]['vector'], [0, 0, G])
        self.assertIsNone(rows[2]['vector'])

    def test_proposal_confirmation_failure_and_model_switch_lifecycle(self):
        fixture = test_mechanical.RequestTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        service = ChatWorkspace(fixture.workspace)
        sid = uuid.uuid4().hex
        service.open_model(sid, fixture.workspace.get(fixture.mid))
        session = service.session(sid)
        def propose_code(code):
            propose(service, sid, 'run_mechanical_code', dict(model_id=fixture.mid, revision=session.revision,
                    title='Gravity', objective='Check gravity', code=code), '')
        propose_code(DOWN)
        self.assertEqual(service.context(sid)['gravityLoads'][0]['state'], 'proposed')
        self.assertEqual(json.loads(service.viewer(sid))['gravityLoads'][0]['vector'], [0, 0, -G])
        self.assertEqual(session.gravity_loads, [])
        consume_confirmation(service, sid, 'No')
        self.assertEqual(service.context(sid)['gravityLoads'], [])
        propose_code(DOWN)
        def runner(*_):
            self.assertEqual(service.context(sid)['gravityLoads'][0]['state'], 'running')
            return {'report': {'status': 'succeeded', 'gravityLoads': [{'id': 'actual', 'vector': [0, 0, -G], 'source': 'mechanical'}]}}
        service.code_runner = runner
        approved = consume_confirmation(service, sid, 'Confirm')
        service.execute_code(sid, approved['arguments'])
        self.assertEqual(service.context(sid)['gravityLoads'][0]['state'], 'applied')
        propose_code(DOWN.replace('Negative', 'Positive'))
        self.assertEqual(service.context(sid)['gravityLoads'][0]['vector'], [0, 0, G])
        consume_confirmation(service, sid, 'No')
        self.assertEqual(service.context(sid)['gravityLoads'][0]['vector'], [0, 0, -G])
        service.code_runner = lambda *_: {'report': {'status': 'failed', 'error': 'test failure'}}
        service.execute_code(sid, dict(model_id=fixture.mid, revision=session.revision, title='Fail', objective='Fail', code=DOWN + 'raise ValueError()'))
        self.assertEqual(service.context(sid)['gravityLoads'], [])
        reused = service.execute_code(sid, dict(model_id=fixture.mid, revision=session.revision, title='Gravity', objective='Reuse result', code=DOWN))
        self.assertTrue(reused['alreadyRun'])
        self.assertEqual(service.context(sid)['gravityLoads'][0]['vector'], [0, 0, -G])
        service.open_model(sid, fixture.workspace.get(fixture.mid))
        self.assertEqual(service.context(sid)['gravityLoads'], [])


if __name__ == '__main__':
    unittest.main()
