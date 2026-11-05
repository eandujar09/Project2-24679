"""Generated-program contracts and agent error correction; no licensed solves here."""
import json
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

import test_mechanical
from gradio_app.chat_agent import ChatAgent
from gradio_app.chat_state import ChatWorkspace
from gradio_app.chat_tools import apply_tool
from gradio_app.simulation import prepare_code_request
from mechanical.contract import validate_request
from mechanical.program import validate_program
from mechanical.transfer import pack_submission, unpack_submission


class ProgramTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_mechanical.RequestTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.workspace, self.mid, self.root = self.fixture.workspace, self.fixture.mid, self.fixture.root
        self.sid = uuid.uuid4().hex

    def program(self, code='print(ctx.geometry)'):
        return {'title': 'Runtime CAD inspection', 'objective': 'Inspect this uploaded CAD.', 'code': code}

    def test_arbitrary_computation_and_mechanical_api_calls_are_not_templates(self):
        code = "import math\na = Model.AddModalAnalysis()\nfor size in [5, 4, 3]:\n    Model.Mesh.ElementSize = Quantity(size, 'mm')\n    ctx.generate_mesh()\n    ctx.solve(a)\n"
        self.assertEqual(len(validate_program(self.program(code))), 64)
        with self.assertRaisesRegex(ValueError, 'does not compile'):
            validate_program(self.program('this is not valid Python!'))

    def test_obvious_system_access_and_direct_unbounded_solve_are_rejected(self):
        for code in ['import os', "open('/tmp/x','w')", 'eval("1")', 'x.__class__', 'a.Solution.Solve(True)']:
            with self.subTest(code=code), self.assertRaises(ValueError):
                validate_program(self.program(code))

    def test_program_upload_does_not_require_legacy_material_or_boundary_setup(self):
        project = self.workspace.get(self.mid)
        for row in project['boundaryConditions']:
            self.workspace.delete_annotation(self.mid, 'boundaryConditions', row['id'], True)
        request = prepare_code_request(self.workspace, self.mid, self.program())
        self.assertEqual(request['schemaVersion'], 2)
        self.assertEqual(validate_request(request), [])
        self.assertNotIn('material', request['settings'])
        destination = self.root / 'new-job'
        destination.mkdir()
        unpacked = unpack_submission(pack_submission(request), destination)
        self.assertEqual(unpacked['program']['code'], self.program()['code'])
        self.assertNotEqual(unpacked['stepFile'], request['stepFile'])

    def test_code_hash_and_mesh_limits_are_validated(self):
        request = prepare_code_request(self.workspace, self.mid, self.program())
        request['program']['code'] += '\nprint(1)'
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            validate_request(request)
        request = prepare_code_request(self.workspace, self.mid, self.program())
        request['settings']['maxMeshEntities'] = 999999
        with self.assertRaisesRegex(ValueError, '32000'):
            validate_request(request)

    def test_code_execution_preserves_source_and_stale_state_cannot_run(self):
        calls = []
        def runner(w, mid, program, selected):
            calls.append(program)
            return {'report': {'status': 'succeeded', 'kind': 'generated-python', 'verifiedSolves': [], 'results': {},
                               'tables': {}, 'metrics': {}, 'images': []}, 'images': []}
        service = ChatWorkspace(self.workspace, code_runner=runner)
        service.open_model(self.sid, self.workspace.get(self.mid))
        c = service.context(self.sid)
        args = dict(model_id=self.mid, revision=c['revision'], **self.program())
        apply_tool(service, self.sid, 'run_mechanical_code', args)
        self.assertEqual(len(calls), 1)
        self.assertEqual(service.session(self.sid).messages[-2]['content']['code'], self.program()['code'])
        with self.assertRaisesRegex(ValueError, 'state changed'):
            apply_tool(service, self.sid, 'run_mechanical_code', args)
        args['revision'] = service.context(self.sid)['revision']
        self.assertTrue(apply_tool(service, self.sid, 'run_mechanical_code', args)['alreadyRun'])
        self.assertEqual(len(calls), 1)

    def test_agent_reads_runtime_error_and_submits_changed_code(self):
        codes = []
        def runner(w, mid, program, selected):
            codes.append(program['code'])
            report = {'status': 'failed' if len(codes) == 1 else 'succeeded', 'kind': 'generated-python',
                      'results': {}, 'tables': {}, 'images': [], 'verifiedSolves': []}
            if len(codes) == 1:
                report.update(error='AttributeError: MissingMember', traceback='actual synthetic exception trace')
            return {'report': report, 'images': []}
        class Model:
            def complete(_, session, prompt):
                data = json.loads(prompt.split('CAD_REQUEST_JSON\n', 1)[1])
                context, observations = data['context'], data['toolObservationsThisTurn']
                if context['lastResult'] and context['lastResult']['status'] == 'succeeded':
                    return json.dumps({'reply': 'Inspection completed; no solve was requested.', 'action': None})
                failed = context['lastResult'] is not None
                if failed:
                    assert 'MissingMember' in context['lastResult']['error']
                code = 'print(ctx.geometry)' if failed else 'print(Model.MissingMember)'
                return json.dumps({'reply': 'Inspect the actual model.', 'action': {'tool': 'run_mechanical_code',
                    'arguments': dict(model_id=context['modelId'], revision=context['revision'],
                                      title='Inspect CAD', objective='Inspect geometry, without solving.', code=code)}})
        service = ChatWorkspace(self.workspace, code_runner=runner)
        service.open_model(self.sid, self.workspace.get(self.mid))
        agent = ChatAgent(service, Model())
        list(agent.turn(self.sid, 'Inspect this model'))
        self.assertEqual(codes, [])
        list(agent.turn(self.sid, 'Confirm'))
        self.assertEqual(codes, ['print(Model.MissingMember)'])
        self.assertIsNotNone(service.session(self.sid).pending_confirmation)
        list(agent.turn(self.sid, 'Confirm'))
        self.assertEqual(codes, ['print(Model.MissingMember)', 'print(ctx.geometry)'])
        self.assertEqual(service.context(self.sid)['lastResult']['status'], 'succeeded')
        self.assertEqual(service.context(self.sid)['lastResult']['verifiedSolves'], [])
        self.assertFalse(service.session(self.sid).running)

    def test_uncertain_submission_is_not_retried_with_identical_code(self):
        calls = []
        def runner(*args):
            calls.append(1)
            raise ValueError('Transport disconnected; the job may still be running.')
        service = ChatWorkspace(self.workspace, code_runner=runner)
        service.open_model(self.sid, self.workspace.get(self.mid))
        for index in range(2):
            args = dict(model_id=self.mid, revision=service.context(self.sid)['revision'], **self.program('print(' + str(index) + ')'))
            with self.assertRaises(ValueError):
                apply_tool(service, self.sid, 'run_mechanical_code', args)
        self.assertEqual(len(calls), 1)


    def test_existing_job_recovery_never_calls_the_code_runner(self):
        from gradio_app.remote import RemoteSubmissionError
        record = self.workspace.root / 'exports/simulations/known/remote-job.json'
        record.parent.mkdir(parents=True)
        record.write_text('{}')
        calls = []
        def runner(*args):
            calls.append(1)
            raise RemoteSubmissionError('Connection interrupted', record)
        service = ChatWorkspace(self.workspace, code_runner=runner)
        service.open_model(self.sid, self.workspace.get(self.mid))
        with self.assertRaises(ValueError):
            apply_tool(service, self.sid, 'run_mechanical_code', dict(model_id=self.mid,
                       revision=service.context(self.sid)['revision'], **self.program()))
        report = {'kind': 'generated-python', 'status': 'succeeded', 'modelId': self.mid,
                  'results': {}, 'images': [], 'verifiedSolves': []}
        with patch('gradio_app.chat_state.recover_job', side_effect=[{'status': 'succeeded'}, report]) as recover:
            result = apply_tool(service, self.sid, 'recover_mechanical_run', dict(model_id=self.mid,
                                revision=service.context(self.sid)['revision']))
        self.assertTrue(result['recovered'])
        self.assertEqual(calls, [1])
        self.assertEqual(recover.call_count, 2)
        self.assertEqual(service.session(self.sid).program_attempts[-1]['status'], 'succeeded')

    def test_multi_solid_step_is_available_to_generated_code(self):
        from OCP.BRep import BRep_Builder
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCP.TopoDS import TopoDS_Compound
        from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
        from OCP.gp import gp_Pnt
        compound = TopoDS_Compound()
        builder = BRep_Builder(); builder.MakeCompound(compound)
        builder.Add(compound, BRepPrimAPI_MakeBox(10,10,10).Shape())
        builder.Add(compound, BRepPrimAPI_MakeBox(gp_Pnt(30,0,0),10,10,10).Shape())
        path = self.root / 'assembly.step'
        writer = STEPControl_Writer(); writer.Transfer(compound, STEPControl_AsIs); writer.Write(str(path))
        project = self.workspace.open_step(path)
        request = prepare_code_request(self.workspace, project['id'], self.program())
        self.assertEqual(len(request['faceSignatures']), 12)
        self.assertIsNone(request['faceMappingWarning'])

    def test_resource_limit_prevents_solver_call(self):
        from mechanical.agent_run import ExecutionContext
        from unittest.mock import Mock
        context = ExecutionContext(None, {}, self.root, {'settings': {'maxMeshEntities': 32000}}, {}, [], {}, {})
        context.mesh_counts = lambda: {'nodes': 33000, 'elements': 15000}
        analysis = Mock()
        with self.assertRaisesRegex(ValueError, 'worker limit'):
            context.solve(analysis)
        analysis.Solution.Solve.assert_not_called()
