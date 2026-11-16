"""Operator-confirmed licensing must not be replaced with stale or inferred failures."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

from fluent.agent_run import license_failure_diagnostic
from gradio_app.chat_agent import instructions
from gradio_app.remote import check_connection


class LicenseStatusTests(unittest.TestCase):
    def test_agent_knows_operator_confirmation_without_fabricating_solve_success(self):
        for mode in ('guided','autonomous'):
            prompt = instructions(mode)
            self.assertIn('licenses are working',prompt)
            self.assertIn('NOT a current setup blocker',prompt)
            self.assertIn('NEW actual',prompt)
            self.assertIn('does not turn old runs into successful solves',prompt)

    def test_successful_license_messages_do_not_mask_other_startup_errors(self):
        for text in ['Fluent license checkout successful.\nConnection refused.',
                     'License feature granted.\nNetwork error.',
                     'Copyright and licensing information.\nFluent startup failed.', '']:
            self.assertIsNone(license_failure_diagnostic(text))

    def test_new_explicit_license_failures_are_still_reported(self):
        for text in ['Unexpected license problem; exiting.', 'ANSYS LICENSE MANAGER ERROR:',
                     'License checkout failed.', 'Unable to obtain a license.', 'License has expired.']:
            self.assertEqual(license_failure_diagnostic(text),text)

    def test_connection_check_does_not_suggest_license_is_broken(self):
        connection = Mock(transport='opencode')
        connection.check.return_value = {'pyMechanicalVersion':'0.12.7','licenseVerified':None,'licenseStatus':'not_checked'}
        with patch('gradio_app.remote.configured_connection',return_value=connection):
            message = check_connection()
        self.assertIn('worker is available',message)
        self.assertNotIn('license',message.lower())

    def test_capability_check_distinguishes_not_checked_from_failed(self):
        root = Path(__file__).resolve().parents[2]
        output = subprocess.check_output([sys.executable,'-m','mechanical.ssh_worker','check'],cwd=root,text=True)
        info = json.loads(output)
        self.assertIsNone(info['licenseVerified'])
        self.assertFalse(info['licenseCheckPerformed'])
        self.assertEqual(info['licenseStatus'],'not_checked')


if __name__ == '__main__':
    unittest.main()
