"""Studio exposes read-only Fluent tooling without authorizing solver work."""
import asyncio
import ast
import json
from pathlib import Path
from unittest.mock import Mock,patch
import unittest

import test_fluent
from fluent.mcp_tools import call_mcp
from gradio_app.chat_tools import apply_tool,tool_schemas
from gradio_app.mcp_server import build_mcp
from gradio_app.remote import check_fluent_worker

NAMES={'find_fluent_api','get_fluent_api_help','validate_fluent_api_code',
       'validate_fluent_program','check_fluent_worker'}


class FluentInspectionTests(unittest.TestCase):
    def setUp(self):
        fixture=test_fluent.FluentTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture;self.service=fixture.service(Mock())
        self.sid=fixture.sid

    def args(self,**values):return self.fixture.args(self.service,**values)

    def test_tools_are_visible_in_both_chat_and_studio_mcp(self):
        self.assertTrue(NAMES <= {t['name'] for t in tool_schemas()})
        tools=asyncio.run(build_mcp(self.service).list_tools())
        self.assertTrue(NAMES <= {t.name for t in tools})

    def test_read_only_calls_keep_conditions_revision_and_attempts_unchanged(self):
        before=self.fixture.workspace.get(self.fixture.mid)
        revision=self.service.context(self.sid)['revision']
        with patch('fluent.mcp_tools.call_mcp',return_value={'response':{'isError':False}}) as mcp:
            apply_tool(self.service,self.sid,'find_fluent_api',self.args(query='residual equations',under='solution'))
            mcp.assert_called_once_with('find_api',{'query':'residual equations','top_k':5,'under':'solution'})
        self.assertEqual(self.fixture.workspace.get(self.fixture.mid),before)
        self.assertEqual(self.service.context(self.sid)['revision'],revision)
        self.assertFalse(self.service.session(self.sid).program_attempts)
        self.service.fluent_runner.assert_not_called()

    def test_help_and_validation_use_official_read_only_tools(self):
        for name,upstream,args in [
            ('get_fluent_api_help','get_help',{'path':'setup.models.viscous.model'}),
            ('validate_fluent_api_code','validate_code',{'code':"solver.settings.setup.models.viscous.model = 'laminar'"})]:
            with self.subTest(name=name),patch('fluent.mcp_tools.call_mcp',return_value={}) as mcp:
                apply_tool(self.service,self.sid,name,self.args(**args))
                mcp.assert_called_once_with(upstream,args)

    def test_stale_or_cross_model_request_never_reaches_mcp(self):
        for args in (dict(self.args(query='mesh'),revision=-1),dict(self.args(query='mesh'),model_id='other')):
            with patch('fluent.mcp_tools.call_mcp') as mcp,self.assertRaises(ValueError):
                apply_tool(self.service,self.sid,'find_fluent_api',args)
            mcp.assert_not_called()

    def test_full_worker_validation_is_labeled_not_mcp_or_live_validation(self):
        result=apply_tool(self.service,self.sid,'validate_fluent_program',self.args(code='print(ctx.geometry)'))
        self.assertTrue(result['valid']);self.assertFalse(result['liveAPIValidated'])
        self.assertEqual(result['validationScope'],'worker-contract')
        self.assertFalse(result['solverLaunched'])
        with self.assertRaisesRegex(ValueError,'removed'):
            apply_tool(self.service,self.sid,'validate_fluent_program',self.args(code='ctx.mesh()'))
        self.assertFalse(self.service.session(self.sid).program_attempts)

    def test_compatibility_is_read_only_and_rejects_old_worker(self):
        connection=Mock()
        for protocol,expected in [(1,False),(2,True)]:
            connection.check.return_value={'pyFluentVersion':'0.37.2','fluentWorkerProtocol':protocol,
                'requiredFluentVersion':261,'licenseStatus':'not_checked','password':'must-not-return'}
            result=check_fluent_worker(connection)
            self.assertEqual(result['compatible'],expected)
            self.assertFalse(result['solverLaunched']);self.assertFalse(result['licenseCheckPerformed'])
            self.assertNotIn('password',json.dumps(result))
        connection.run.assert_not_called()

    def test_chat_can_check_worker_without_running_or_proposing_a_job(self):
        with patch('gradio_app.remote.check_fluent_worker',return_value={'compatible':True,'solverLaunched':False}) as check:
            result=apply_tool(self.service,self.sid,'check_fluent_worker',self.args())
        self.assertTrue(result['compatible']);check.assert_called_once_with()
        self.assertFalse(self.service.session(self.sid).program_attempts)
        self.assertIsNone(self.service.session(self.sid).pending_confirmation)
        self.service.fluent_runner.assert_not_called()

    def test_mutating_mcp_tools_are_not_exposed(self):
        for name in ('run_code','connect','disconnect','manage_fluent'):
            with self.subTest(name=name),patch('fluent.mcp_tools.subprocess.run') as run,self.assertRaises(ValueError):
                call_mcp(name,{})
            run.assert_not_called()

    def test_adapter_preserves_upstream_validation_errors_and_strips_credentials(self):
        response={'isError':False,'structuredContent':{'status':'error','message':'Names not in sandbox: ctx'}}
        completed=Mock(returncode=0,stdout=json.dumps(response))
        with patch.dict('os.environ',{'FLUENT_MCP_PYTHON':str(Path(__file__).resolve()),'OPENAI_API_KEY':'private-key'}),\
             patch('fluent.mcp_tools.subprocess.run',return_value=completed) as run:
            result=call_mcp('validate_code',{'code':'ctx.solve()'})
        self.assertEqual(result['response'],response)
        self.assertFalse(result['solverLaunched'])
        self.assertNotIn('OPENAI_API_KEY',run.call_args.kwargs['env'])
        self.assertNotIn('valid',result)

    def test_query_size_and_unknown_arguments_are_rejected(self):
        for args in (self.args(query='mesh',top_k=100),self.args(query='mesh',command='run_code')):
            with self.assertRaises(ValueError):apply_tool(self.service,self.sid,'find_fluent_api',args)

    def test_worker_catalog_is_forwarded_using_official_server_option(self):
        file=Path(__file__).resolve()
        completed=Mock(returncode=0,stdout='{"isError":false}')
        with patch.dict('os.environ',{'FLUENT_MCP_PYTHON':str(file),'FLUENT_MCP_API_OBJECTS_PATH':str(file)}),\
             patch('fluent.mcp_tools.subprocess.run',return_value=completed) as run:
            result=call_mcp('find_api',{'query':'mesh'})
        self.assertEqual(result['catalogSource'],'configured-worker')
        self.assertEqual(run.call_args.kwargs['env']['FLUIDS_MCP_API_OBJECTS_PATH'],str(file))

    def test_launcher_accepts_the_new_private_configuration_keys(self):
        path=Path(__file__).resolve().parents[2]/'scripts/run_mac.py'
        tree=ast.parse(path.read_text())
        sets=[ast.literal_eval(node) for node in ast.walk(tree) if isinstance(node,ast.Set)]
        self.assertTrue(any({'FLUENT_MCP_PYTHON','FLUENT_MCP_API_OBJECTS_PATH',
                             'FLUENT_POST_PYTHON','FLUENT_POST_SERVER'}<=values for values in sets))


if __name__=='__main__':unittest.main()
