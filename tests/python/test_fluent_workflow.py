"""Seamless chat data, authored guidance and native post-only result safety."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch

import test_fluent
from fluent.postprocessing import render_result
from gradio_app.chat_agent import ChatAgent
from gradio_app.chat_context import bounded, result_summary
from gradio_app.chat_tools import apply_tool, tool_schemas
from gradio_app.mcp_server import build_mcp


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        f = test_fluent.FluentTests(); f.setUp(); self.addCleanup(f.doCleanups)
        self.fixture, self.service, self.sid = f, f.service(Mock()), f.sid

    def test_review_is_read_only_and_returns_adaptable_source(self):
        before = self.fixture.workspace.get(self.fixture.mid)
        result = apply_tool(self.service,self.sid,'review_fluent_workflow',self.fixture.args(self.service))
        self.assertEqual(before,self.fixture.workspace.get(self.fixture.mid))
        self.assertEqual(result['conditionCount'],6)
        self.assertEqual(result['unassignedFaceKeys'],[])
        self.assertIn("'OneZonePer': 'face'",result['exampleCode'])
        self.assertEqual(bounded(result)['exampleCode'],result['exampleCode'])
        self.assertFalse(self.service.session(self.sid).program_attempts)

    def test_new_tools_visible_in_both_action_boundaries(self):
        import asyncio
        names={'review_fluent_workflow','render_fluent_results'}
        self.assertTrue(names<={t['name'] for t in tool_schemas()})
        self.assertTrue(names<={t.name for t in asyncio.run(build_mcp(self.service).list_tools())})

    def test_large_result_diagnostics_do_not_inflate_context_or_mutate_artifacts(self):
        report={'status':'failed','error':'mapping failed', 'geometry':{'faces':[{'samples':['x'*1000]*1000}]*18},
                'stdout':'a'*100000,'tables':{'residuals':[{'continuity':1e-6}]*2000},'verifiedSolves':[]}
        original=copy.deepcopy(report)
        summary=result_summary(report)
        self.assertLess(len(json.dumps(summary)),20000)
        self.assertEqual(summary['error'],'mapping failed')
        self.assertEqual(summary['geometry']['faceCount'],18)
        self.assertEqual(report,original)

    def test_discovery_answer_reaches_agent_and_identical_inspection_is_cached(self):
        calls=[]
        class Model:
            def complete(_,session,prompt):
                data=json.loads(prompt.split('CAD_REQUEST_JSON\n',1)[1])
                observations=data['toolObservationsThisTurn'];calls.append(data)
                if len(calls)<3:
                    if observations:
                        self.assertIn('setup.models.viscous.model',json.dumps(observations))
                    return json.dumps({'reply':'Inspecting API.','action':{'tool':'find_fluent_api',
                        'arguments':dict(model_id=data['context']['modelId'],revision=data['context']['revision'],query='viscous')}})
                return json.dumps({'reply':'API found; no solve requested.','action':None})
        with patch('fluent.mcp_tools.call_mcp',return_value={'path':'setup.models.viscous.model'}) as mcp:
            list(ChatAgent(self.service,Model()).turn(self.sid,'Inspect the Fluent API'))
        mcp.assert_called_once()
        self.service.fluent_runner.assert_not_called()

    def test_explicit_postprocessing_blocks_unknown_job(self):
        self.service.session(self.sid).program_attempts.append({'status':'unknown'})
        with patch('fluent.postprocessing.render_result') as render,self.assertRaises(ValueError):
            apply_tool(self.service,self.sid,'render_fluent_results',self.fixture.args(self.service))
        render.assert_not_called()


class NativePostTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);(self.root/'results').mkdir()
        source=b'exact CAD';digest=hashlib.sha256(source).hexdigest()
        (self.root/'results/source.step').write_bytes(source)
        (self.root/'request.json').write_text(json.dumps({'modelId':digest,'sourceFaces':[{'key':'face1'}]}))
        (self.root/'results/face-mapping.json').write_text(json.dumps({'faceZones':{'face1':'verified-zone'}}))
        self.report={'status':'succeeded','kind':'generated-python','solver':'fluent','converged':True,
            'modelId':digest,'verifiedSolves':[{'status':'Done'}],'images':[]}
        self.result={'directory':self.root,'report':self.report,'images':[]}
        self.config={'FLUENT_POST_PYTHON':str(Path(__file__)),'FLUENT_POST_SERVER':str(Path(__file__))}

    def test_failed_or_unverified_solve_never_launches_post(self):
        for updates in ({'status':'failed'},{'converged':False},{'verifiedSolves':[]}):
            with self.subTest(updates=updates),patch('fluent.postprocessing.subprocess.run') as run,self.assertRaises(ValueError):
                render_result(dict(self.result,report=dict(self.report,**updates)))
            run.assert_not_called()

    def test_native_images_are_archived_without_changing_convergence(self):
        images=[{'file':n,'label':'Native Fluent'} for n in ('native-pressure.png','native-velocity.png')]
        for i in images:(self.root/'results'/i['file']).write_bytes(b'PNG data')
        with patch.dict(os.environ,self.config),patch('fluent.postprocessing.subprocess.run',
                return_value=Mock(returncode=0,stdout=json.dumps({'images':images}))) as run:
            result=render_result(self.result)
        self.assertTrue(result['report']['converged'])
        self.assertEqual(result['report']['nativePostprocessing']['status'],'succeeded')
        self.assertEqual(len(result['images']),2)
        self.assertTrue((self.root/'simulation.zip').is_file())
        self.assertNotIn('OPENAI_API_KEY',run.call_args.kwargs['env'])

    def test_timeout_retains_solve_and_blocks_automatic_retry(self):
        with patch.dict(os.environ,self.config),patch('fluent.postprocessing.subprocess.run',
                side_effect=subprocess.TimeoutExpired('native',300)) as run:
            result=render_result(self.result)
            with self.assertRaisesRegex(ValueError,'uncertain'):render_result(result)
        run.assert_called_once()
        self.assertEqual(result['report']['status'],'succeeded')
        self.assertTrue(result['report']['converged'])
        self.assertEqual(result['report']['nativePostprocessing']['status'],'unknown')

    def test_changed_cad_never_reaches_native_server(self):
        (self.root/'results/source.step').write_bytes(b'changed')
        with patch.dict(os.environ,self.config),patch('fluent.postprocessing.subprocess.run') as run:
            result=render_result(self.result)
        run.assert_not_called()
        self.assertEqual(result['report']['nativePostprocessing']['status'],'failed')
        self.assertTrue(result['report']['converged'])


if __name__=='__main__':unittest.main()
