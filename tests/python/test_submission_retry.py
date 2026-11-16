"""Only proven pre-submission failures may bypass solver-job deduplication."""
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

import test_fluent
from gradio_app.chat_state import ChatWorkspace
from gradio_app.chat_tools import apply_tool
from gradio_app.remote import (PreSubmissionError,RemoteSubmissionError,definite_non_submission,
                               LEGACY_FLUENT_PREFLIGHT_ERRORS,submit_remote_request)
from gradio_app.simulation import prepare_fluent_request


def completed():
    return {'report':{'kind':'generated-python','solver':'fluent','status':'succeeded',
                      'verifiedSolves':[],'tables':{},'images':[]},'images':[]}


class SubmissionRetryTests(unittest.TestCase):
    def setUp(self):
        fixture = test_fluent.FluentTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.workspace,self.mid,self.sid = fixture.workspace,fixture.mid,fixture.sid

    def run_code(self,service,solver='fluent'):
        args = dict(model_id=self.mid,revision=service.context(self.sid)['revision'],**test_fluent.PROGRAM)
        return apply_tool(service,self.sid,'run_'+solver+'_code',args)

    def test_same_fluent_program_can_retry_preflight_then_deduplicates_actual_completion(self):
        runner = Mock(side_effect=[PreSubmissionError('Missing worker'),PreSubmissionError('Missing worker'),completed()])
        service = self.fixture.service(runner)
        for _ in range(2):
            with self.assertRaisesRegex(PreSubmissionError,'Missing worker'):
                self.run_code(service)
            attempt = service.context(self.sid)['programAttempts'][-1]
            self.assertEqual(attempt['status'],'not_submitted')
            self.assertTrue(attempt['retryable'])
            self.assertFalse(attempt['recoverable'])
        self.assertTrue(self.run_code(service)['artifactsReady'])
        self.assertTrue(self.run_code(service)['alreadyRun'])
        self.assertEqual(runner.call_count,3)
        self.assertEqual(len(service.session(self.sid).program_attempts),3)

    def test_same_mechanical_program_retries_only_a_typed_preflight_failure(self):
        runner = Mock(side_effect=[PreSubmissionError('Worker unavailable'),completed()])
        service = ChatWorkspace(self.workspace,code_runner=runner)
        service.open_model(self.sid,self.workspace.get(self.mid))
        with self.assertRaises(PreSubmissionError):
            self.run_code(service,'mechanical')
        self.assertTrue(self.run_code(service,'mechanical')['artifactsReady'])
        self.assertEqual(runner.call_count,2)

    def test_legacy_structural_preset_releases_only_a_proven_preflight_fingerprint(self):
        runner = Mock(side_effect=[PreSubmissionError('Worker unavailable'),completed()])
        service = ChatWorkspace(self.workspace,runner=runner)
        service.open_model(self.sid,self.workspace.get(self.mid))
        session = service.session(self.sid)
        session.material,session.small_deformation = 'Structural Steel',True
        args = lambda: dict(model_id=self.mid,revision=service.context(self.sid)['revision'])
        with self.assertRaises(PreSubmissionError):
            apply_tool(service,self.sid,'run_simulation',args())
        self.assertIsNone(session.last_fingerprint)
        self.assertTrue(apply_tool(service,self.sid,'run_simulation',args())['artifactsReady'])
        self.assertEqual(runner.call_count,2)

    def test_known_legacy_failed_capability_attempt_is_retained_but_does_not_block(self):
        runner = Mock(side_effect=[PreSubmissionError('Initial preflight'),completed()])
        service = self.fixture.service(runner)
        with self.assertRaises(PreSubmissionError):
            self.run_code(service)
        old = service.session(self.sid).program_attempts[0]
        old.pop('submissionState'); old.pop('retryable')
        old.update(status='failed',error=next(iter(LEGACY_FLUENT_PREFLIGHT_ERRORS)))
        self.assertTrue(self.run_code(service)['artifactsReady'])
        self.assertEqual(old['status'],'not_submitted')
        self.assertEqual(len(service.session(self.sid).program_attempts),2)

    def test_unknown_fluent_exception_with_no_record_is_not_silently_cleared(self):
        runner = Mock(side_effect=ValueError('Connection broke at an unknown stage'))
        service = self.fixture.service(runner)
        with self.assertRaises(ValueError):
            self.run_code(service)
        with self.assertRaisesRegex(ValueError,'uncertain'):
            self.run_code(service)
        runner.assert_called_once()
        self.assertEqual(service.session(self.sid).program_attempts[0]['status'],'unknown')

    def test_actual_remote_job_and_completed_reports_are_never_legacy_migrated(self):
        old = dict(solver='fluent',status='failed',error=next(iter(LEGACY_FLUENT_PREFLIGHT_ERRORS)))
        self.assertTrue(definite_non_submission(old))
        for extra in [{'recordPath':'remote-job.json'},{'recoverable':True},{'jobId':'job'},
                      {'report':{'status':'failed'}},{'result':{'report':{'status':'failed'}}}]:
            self.assertFalse(definite_non_submission(dict(old,**extra)))
        self.assertFalse(definite_non_submission(dict(old,error='Arbitrary failure')))
        self.assertFalse(definite_non_submission(dict(old,status='unknown')))

    def connection(self):
        connection = Mock(transport='opencode',host='http://test-worker',directory='C:\\worker',
                          python='C:\\python.exe',platform='windows')
        connection.check.return_value = {'pyFluentVersion':'0.37.2','fluentWorkerProtocol':2}
        return connection

    def test_capability_and_packaging_failures_are_typed_non_submissions(self):
        request = prepare_fluent_request(self.workspace,self.mid,test_fluent.PROGRAM)
        connection = self.connection()
        connection.check.return_value = {'pyMechanicalVersion':'0.12.7'}
        with self.assertRaises(PreSubmissionError) as caught:
            submit_remote_request(self.workspace,request,connection=connection)
        self.assertEqual(caught.exception.submission_state,'not_submitted')
        connection.run.assert_not_called()
        connection = self.connection()
        with patch('gradio_app.remote.pack_submission',side_effect=OSError('Local input unavailable')):
            with self.assertRaises(PreSubmissionError):
                submit_remote_request(self.workspace,request,connection=connection)
        connection.run.assert_not_called()

    def test_transport_or_result_validation_failure_retains_recoverable_job_identity(self):
        request = prepare_fluent_request(self.workspace,self.mid,test_fluent.PROGRAM)
        for error_stage in ('transport','results'):
            with self.subTest(stage=error_stage):
                connection = self.connection()
                if error_stage == 'transport':
                    connection.run.side_effect = RuntimeError('Remote submission interrupted')
                with patch('gradio_app.remote.extract_results',side_effect=ValueError('Results identity mismatch')):
                    with self.assertRaises(RemoteSubmissionError) as caught:
                        submit_remote_request(self.workspace,request,connection=connection)
                self.assertEqual(caught.exception.submission_state,'unknown')
                self.assertTrue(Path(caught.exception.record_path).is_file())
                connection.run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
