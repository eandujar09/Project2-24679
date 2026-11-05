from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from mechanical.native_exports import save_native_exports


class NativeExportsTests(unittest.TestCase):
    def test_archive_includes_results_and_user_files_before_database_export(self):
        events = []
        archive = Mock(side_effect=lambda *args: events.append('archive'))
        settings = Mock(return_value='with-results')
        app = Mock()
        app.save_as.side_effect = lambda *args, **kwargs: events.append('mechdat')
        ns = {'Model': SimpleNamespace(Analyses=[SimpleNamespace(Solution=SimpleNamespace(Status='Done'))]),
              'Ansys': SimpleNamespace(ACT=SimpleNamespace(Automation=SimpleNamespace(
                  Mechanical=SimpleNamespace(ArchiveSettings=settings)))),
              'ExtAPI': SimpleNamespace(DataModel=SimpleNamespace(Project=SimpleNamespace(Archive=archive)))}
        report = {'verifiedSolves': [{'status': 'Done'}]}
        save_native_exports(app, ns, Path('/job'), report)
        settings.assert_called_once_with(True, True)
        archive.assert_called_once_with(str(Path('/job/simulation.mechpz')), True, 'with-results')
        self.assertEqual(events, ['archive', 'mechdat'])
        self.assertTrue(report['nativeArchive']['includesResults'])
        for report in ({'verifiedSolves': []}, {'verifiedSolves': [{'status': 'failed'}]}):
            archive.reset_mock()
            save_native_exports(app, ns, Path('/job'), report)
            archive.assert_not_called()
        # A historical verified solve is insufficient after code changes the model.
        ns['Model'].Analyses[0].Solution.Status = 'SolveRequired'
        archive.reset_mock()
        save_native_exports(app, ns, Path('/job'), {'verifiedSolves': [{'status': 'Done'}]})
        archive.assert_not_called()
        ns['Model'].Analyses = []
        app.save_as.reset_mock()
        save_native_exports(app, ns, Path('/job'), {})
        app.save_as.assert_not_called()
