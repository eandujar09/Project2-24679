"""CFD contracts, state/approval and bounded execution. No license required."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import Mock, patch

import numpy as np
import test_mechanical
from fluent.contract import condition_values, validate_program, validate_request
from fluent.agent_run import ExecutionContext, run
from fluent.mapping import triangulate, match_zones
from gradio_app.chat_agent import ChatAgent
from gradio_app.chat_state import ChatWorkspace
from gradio_app.chat_tools import apply_tool
from gradio_app.chat_confirmations import propose, consume_confirmation, proposed_conditions
from gradio_app.simulation import prepare_code_request, prepare_fluent_request
from mechanical.transfer import pack_submission, unpack_submission


ANALYSIS = dict(domain='fluid-volume', regime='steady-laminar-incompressible', density=1000,
                dynamic_viscosity=0.001, operating_pressure=101325, mesh_size_mm=3,
                max_iterations=100, residual_tolerance=1e-5, mass_imbalance_tolerance=0.01)
PROGRAM = dict(title='Fluid-volume flow', objective='Solve the agreed laminar flow.',
               code='solver = ctx.generate_mesh()\nctx.solve()')


class FluentTests(unittest.TestCase):
    def setUp(self):
        fixture = test_mechanical.RequestTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.workspace, self.mid, self.root = fixture.workspace, fixture.mid, fixture.root
        self.workspace.set_fluent_analysis(self.mid, ANALYSIS)
        self.faces = self.workspace.get(self.mid)['faces']
        for i, face in enumerate(self.faces):
            kind, values = ('velocity_inlet', dict(x=0.01, y=0, z=0)) if i == 0 else ('pressure_outlet', {'gauge_pressure': 0}) if i == 1 else ('wall', {})
            self.workspace.save_annotation(self.mid, face['key'], 'boundaryConditions', dict(type=kind, values=values))
        self.sid = uuid.uuid4().hex

    def service(self, runner=None):
        service = ChatWorkspace(self.workspace, fluent_runner=runner)
        service.open_model(self.sid, self.workspace.get(self.mid))
        return service

    def args(self, service, **values):
        return dict(model_id=self.mid, revision=service.context(self.sid)['revision'], **values)

    def test_si_condition_values_and_zero_gauge_outlet(self):
        self.assertEqual(condition_values('pressure_outlet', {'gauge_pressure': 0}), {'gauge_pressure': 0})
        for kind, values in [('pressure_outlet', {'magnitude': 1}), ('velocity_inlet', dict(x=0,y=0,z=0)),
                             ('velocity_inlet', dict(x=float('nan'),y=0,z=0)), ('wall', {'temperature': 300})]:
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                condition_values(kind, values)

    def test_snapshot_and_transfer_isolate_fluent_and_mechanical_physics(self):
        request = prepare_fluent_request(self.workspace, self.mid, PROGRAM)
        self.assertEqual(len(validate_request(request)), 6)
        mechanical = prepare_code_request(self.workspace, self.mid, dict(PROGRAM, code='print(ctx.geometry)'))
        self.assertTrue(all(r['type'] not in ('wall','velocity_inlet','pressure_outlet') for r in mechanical['boundaryConditions']))
        destination = self.root / 'received'; destination.mkdir()
        result = unpack_submission(pack_submission(request), destination)
        self.assertEqual(result['solver'], 'fluent')
        self.assertEqual(result['program']['code'], PROGRAM['code'])
        self.assertEqual(result['analysis'], ANALYSIS)

    def test_hash_settings_saved_assumptions_and_execution_mode_are_required(self):
        original = prepare_fluent_request(self.workspace, self.mid, PROGRAM)
        for key, value in [('modelId', 'x' * 64), ('analysis', dict(ANALYSIS, regime='turbulent')),
                           ('settings', dict(original['settings'], maxCells=50000)),
                            ('executionMode','fixed-template-v1')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_request(dict(original, **{key: value}))

    def test_changed_face_metadata_is_not_silently_reassigned(self):
        with self.workspace.connect() as db:
            project = self.workspace.get(self.mid)
            project['faces'][0]['centroidMm'][0] += 1
            self.workspace._write(db, project)
        with self.assertRaisesRegex(ValueError, 'Stored face geometry'):
            prepare_fluent_request(self.workspace,self.mid,PROGRAM)

    def test_fluent_analysis_is_persisted_and_shared_between_sessions(self):
        service = self.service()
        second = uuid.uuid4().hex
        service.open_model(second, self.workspace.get(self.mid))
        revision = service.context(second)['revision']
        apply_tool(service, self.sid, 'set_fluent_analysis', self.args(service, **dict(ANALYSIS, density=998)))
        self.assertEqual(self.workspace.get(self.mid)['fluentAnalysis']['density'], 998)
        self.assertGreater(service.context(second)['revision'], revision)

    def test_fluid_conflicts_fail_but_structural_conditions_can_coexist(self):
        service = self.service()
        args = self.args(service, face_key=self.faces[0]['key'], kind='wall', values={})
        with self.assertRaisesRegex(ValueError, 'only one'):
            apply_tool(service, self.sid, 'apply_condition', args)
        # A structural condition already exists on face 0 in this fixture.
        fluid = next(r for r in self.workspace.get(self.mid)['boundaryConditions'] if r['type'] == 'velocity_inlet')
        args = self.args(service, face_key=self.faces[0]['key'], kind='velocity_inlet', values=dict(x=0.02,y=0,z=0), record_id=fluid['id'])
        apply_tool(service, self.sid, 'apply_condition', args)

    def test_guided_code_and_conditions_require_exact_fresh_confirmation(self):
        runner = Mock()
        service = self.service(runner)
        fluid = next(r for r in self.workspace.get(self.mid)['boundaryConditions'] if r['type'] == 'velocity_inlet')
        args = self.args(service, face_key=self.faces[0]['key'], kind='velocity_inlet', values=dict(x=0.02,y=0,z=0), record_id=fluid['id'])
        propose(service, self.sid, 'apply_condition', args, 'Preview the inlet.')
        self.assertEqual(proposed_conditions(service, service.session(self.sid))[0]['values']['x'], 0.02)
        self.assertEqual(next(r for r in self.workspace.get(self.mid)['boundaryConditions'] if r['id'] == fluid['id'])['values']['x'], 0.01)
        propose(service, self.sid, 'run_fluent_code', self.args(service, **PROGRAM), 'Run Fluent.')
        runner.assert_not_called()
        # Another window's setup changes invalidate the proposal even without a click.
        self.workspace.set_fluent_analysis(self.mid, dict(ANALYSIS, density=999))
        self.assertIsNone(consume_confirmation(service, self.sid, 'Confirm'))
        runner.assert_not_called()

    def test_generated_code_misuse_checks(self):
        self.assertEqual(len(validate_program(PROGRAM)), 64)
        for code in ['import os', 'ctx.solver.tui.file.read_case("x")',
                     'solver.settings.solution.run_calculation.iterate(iter_count=999999)',
                     'x.launch_fluent()', 'ctx.solver.scheme.eval("x")', 'open("x")']:
            with self.subTest(code=code), self.assertRaises(ValueError):
                validate_program(dict(PROGRAM, code=code))

    def test_agent_uses_same_confirmation_and_result_flow_for_fluent(self):
        runner = Mock(return_value={'report': {'kind': 'generated-python', 'solver': 'fluent',
             'status': 'succeeded', 'converged': True, 'verifiedSolves': [{'status':'Done'}],
             'tables': {}, 'images': []}, 'images': []})
        service = self.service(runner)
        class Model:
            def complete(_, session, prompt):
                c = json.loads(prompt.split('CAD_REQUEST_JSON\n')[1])['context']
                if c['lastResult']:
                    return json.dumps({'reply':'The Fluent report meets the agreed criteria.', 'action':None})
                return json.dumps({'reply':'Propose the agreed CFD run.', 'action': {'tool':'run_fluent_code',
                    'arguments':dict(model_id=c['modelId'],revision=c['revision'],**PROGRAM)}})
        agent = ChatAgent(service, Model())
        list(agent.turn(self.sid, 'Analyze the fluid volume.'))
        runner.assert_not_called()
        list(agent.turn(self.sid, 'Confirm'))
        runner.assert_called_once()
        self.assertTrue(any('verified Fluent' in str(m['content']) for m in service.session(self.sid).messages))
        result = apply_tool(service, self.sid, 'run_fluent_code', self.args(service, **PROGRAM))
        self.assertTrue(result['alreadyRun']); runner.assert_called_once()

    def test_removed_template_failure_is_not_an_uncertain_submission(self):
        service = self.service()
        self.workspace.set_fluent_analysis(self.mid, ANALYSIS)
        wall = next(r for r in self.workspace.get(self.mid)['boundaryConditions'] if r['type'] == 'wall')
        self.workspace.delete_annotation(self.mid, 'boundaryConditions', wall['id'], True)
        with self.assertRaisesRegex(ValueError, 'removed'):
            apply_tool(service, self.sid, 'run_fluent_code', self.args(service, **dict(PROGRAM,code='ctx.mesh()')))
        self.assertFalse(service.session(self.sid).program_attempts)

    def test_mapping_uses_geometry_not_names_and_refuses_ambiguity(self):
        vertices = [[0,0,0],[1,0,0],[1,1,0],[0,1,0]]
        mesh = triangulate(vertices, [4,0,1,2,3])
        signature = dict(key='cad-face', areaMm2=1, samples=[{'pointMm':[0.5,0.5,0]}],
                         verticesMm=vertices, edges=[{'pointsMm':vertices}])
        mapping, evidence = match_zones([signature], {'unrelated-zone-name':mesh}, lambda k,p:0, 0.01)
        self.assertEqual(mapping, {'cad-face':'unrelated-zone-name'})
        self.assertLess(evidence[0]['reverseErrorMm'], 0.01)
        with self.assertRaisesRegex(ValueError, 'split'):
            match_zones([signature], {'a':mesh,'b':mesh}, lambda k,p:0, 0.01)
        with self.assertRaisesRegex(ValueError, 'unique'):
            match_zones([signature, dict(signature,key='other')], {'a':mesh,'b':mesh}, lambda k,p:0, 0.01)
        with self.assertRaisesRegex(ValueError, 'unique'):
            match_zones([signature], {'a':mesh}, lambda k,p:1, 0.01)

    def test_cell_cap_blocks_iteration(self):
        ctx = ExecutionContext({'analysis': ANALYSIS, 'boundaryConditions': [],
                                'settings': {'maxCells':32000}}, self.root, {})
        ctx.solver = Mock()
        ctx.solver.settings.setup.cell_zone_conditions.fluid.get_object_names.return_value = ['fluid']
        ctx.solver.settings.setup.cell_zone_conditions.solid.get_object_names.return_value = []
        ctx.solver.fields.solution_variable_info.get_zones_info.return_value = {'fluid':SimpleNamespace(count=32001)}
        ctx._configured = True
        ctx._mapping = {'face':'wall'}
        with self.assertRaisesRegex(ValueError, '32000'):
            ctx.solve()
        ctx.solver.settings.solution.run_calculation.iterate.assert_not_called()

    def test_inspection_completes_without_claiming_a_solve_and_keeps_source(self):
        request = prepare_fluent_request(self.workspace, self.mid, dict(PROGRAM, code='print(ctx.analysis)'))
        context=Mock(analysis=ANALYSIS,geometry={'faces':[]},solver=None,_iterated=False)
        report = run(request, self.root/'no-solve',context_factory=lambda *a:context)
        self.assertEqual(report['status'], 'succeeded')
        self.assertEqual(report['verifiedSolves'],[])
        self.assertFalse(report['converged'])
        context.prepare.assert_called_once_with()
        self.assertTrue((self.root/'no-solve'/'agent.py').is_file())

    def solve_context(self, residual=1e-6, outlet=1.0):
        request = dict(analysis=ANALYSIS, boundaryConditions=[
            dict(faceKey='in',type='velocity_inlet',values=dict(x=1,y=0,z=0)),
            dict(faceKey='out',type='pressure_outlet',values={'gauge_pressure':0})],
            settings={'maxCells':32000})
        report = dict(metrics={},tables={},verifiedSolves=[],mesh={'cells':100})
        ctx = ExecutionContext(request, self.root, report)
        ctx._configured = True; ctx._mapping = {'in':'inlet','out':'outlet'}
        ctx.solver = Mock()
        ctx.solver.settings.setup.general.solver.time.return_value = 'steady'
        for name in ('models','general','cell_zone_conditions','materials','boundary_conditions'):
            getattr(ctx.solver.settings.setup,name).get_state.return_value = {}
        ctx.solver.settings.setup.boundary_conditions.get_state.return_value = {
            'velocity_inlet':{'inlet':{}},'pressure_outlet':{'outlet':{}}}
        ctx.mesh_counts = Mock(return_value={'cells':100})
        ctx.solver.settings.solution.methods.get_state.return_value = {}
        ctx.solver.settings.solution.controls.get_state.return_value = {}
        ctx._assert_setup = Mock()
        ctx.save_case = Mock()
        required = ['continuity','x-velocity','y-velocity','z-velocity']
        equations = {name:Mock() for name in required}
        group = Mock(); group.get_object_names.return_value = required
        group.__getitem__ = Mock(side_effect=equations.__getitem__)
        ctx.solver.settings.solution.monitor.residual.equations = group
        ctx.solver.monitors.get_monitor_set_data.return_value = ([1,2], {name:[0.01,residual] for name in required})
        ctx.solver.fields.reduction.mass_flow_integral.side_effect = [-1.0,outlet]
        return ctx

    def test_residual_and_mass_balance_both_required_for_success(self):
        for residual, outlet, converged in [(1e-6,1,True),(0.1,1,False),(1e-6,0.5,False)]:
            with self.subTest(residual=residual,outlet=outlet):
                ctx = self.solve_context(residual,outlet)
                if converged:
                    self.assertEqual(ctx.solve()['status'], 'Done')
                else:
                    with self.assertRaisesRegex(ValueError, 'not met'):
                        ctx.solve()
                    self.assertEqual(ctx.report['verifiedSolves'][0]['status'], 'NotConverged')
                self.assertEqual(ctx.report['converged'], converged)
                ctx.save_case.assert_called_once()
                ctx.solver.settings.solution.run_calculation.iterate.assert_called_once_with(iter_count=100)

    def test_missing_residual_history_fails_closed(self):
        ctx = self.solve_context()
        ctx.solver.monitors.get_monitor_set_data.return_value = ([], {})
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            ctx.solve()
        self.assertFalse(ctx.report['verifiedSolves'])

    def test_remote_capability_rejects_old_worker_before_submission(self):
        from gradio_app.remote import run_remote_fluent_code
        connection = Mock()
        connection.check.return_value = {'pyMechanicalVersion':'0.12.7'}
        with self.assertRaisesRegex(ValueError, 'Deploy the Fluent worker'):
            run_remote_fluent_code(self.workspace,self.mid,PROGRAM,connection=connection)
        connection.run.assert_not_called()

    def test_mcp_advertises_typed_fluent_tools_and_shared_runtime(self):
        import asyncio
        from gradio_app.mcp_server import build_mcp
        mcp = build_mcp(self.service())
        tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
        self.assertTrue({'set_fluent_analysis','run_fluent_code','recover_fluent_run'}.issubset(tools))
        self.assertIn('density', tools['set_fluent_analysis'].inputSchema['properties'])
        self.assertIn('velocity_inlet', tools['apply_condition'].inputSchema['properties']['kind']['enum'])

    def test_uncertain_fluent_job_is_recovered_without_resubmission(self):
        from gradio_app.remote import RemoteSubmissionError
        record = self.workspace.root/'exports'/'simulations'/'fluent-known'/'remote-job.json'
        record.parent.mkdir(parents=True); record.write_text('{}')
        runner = Mock(side_effect=RemoteSubmissionError('Transport interrupted',record))
        service = self.service(runner)
        with self.assertRaises(ValueError):
            apply_tool(service,self.sid,'run_fluent_code',self.args(service,**PROGRAM))
        with self.assertRaisesRegex(ValueError,'uncertain'):
            apply_tool(service,self.sid,'run_fluent_code',self.args(service,**dict(PROGRAM,code=PROGRAM['code']+'\nprint(1)')))
        report = dict(kind='generated-python',solver='fluent',status='succeeded',converged=True,
                      verifiedSolves=[{'status':'Done'}],tables={},images=[])
        with patch('gradio_app.chat_state.recover_job',side_effect=[{'status':'succeeded'},report]):
            result = apply_tool(service,self.sid,'recover_fluent_run',self.args(service))
        self.assertTrue(result['recovered']); runner.assert_called_once()


if __name__ == '__main__':
    unittest.main()
