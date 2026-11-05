import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gradio_app.chat_state import ChatWorkspace
from gradio_app.mechanical_export import export_mechanical, export_options, setup_program
from gradio_app.studio import install_studio
from mechanical.execution import result_files
from mechanical.program import validate_program
import test_mechanical


class MechanicalExportTests(unittest.TestCase):
    def setUp(self):
        fixture = test_mechanical.RequestTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.workspace, self.mid = fixture.workspace, fixture.mid
        self.runner = Mock(side_effect=self.make_export)
        self.service = ChatWorkspace(self.workspace, code_runner=self.runner)
        self.sid = 'e' * 32
        self.service.open_model(self.sid, self.workspace.get(self.mid))
        self.session = self.service.session(self.sid)
        self.session.material, self.session.small_deformation = 'Structural Steel', True

    def make_export(self, *args, **kwargs):
        directory = self.workspace.root / 'exports' / str(self.runner.call_count)
        (directory / 'results').mkdir(parents=True)
        (directory / 'results/setup.mechdat').write_bytes(b'native-test-fixture')
        return result_files(directory, {'status': 'succeeded', 'kind': 'generated-python', 'verifiedSolves': []})

    def export(self):
        return export_mechanical(self.service, self.sid, self.mid, self.session.revision)

    def test_exports_confirmed_values_without_meshing_solving_or_applying_proposal(self):
        pending = {'tool': 'apply_condition', 'arguments': {'kind': 'force', 'values': {'z': -999}}}
        self.session.pending_confirmation = pending
        path = self.export()
        self.assertEqual(path.suffix, '.mechdat')
        self.assertIsNone(self.session.result)
        self.assertEqual(self.session.pending_confirmation, pending)
        program = self.runner.call_args.args[2]
        validate_program(program)
        loads = []
        def new_load():
            load = SimpleNamespace(**{a + 'Component': SimpleNamespace(Output=SimpleNamespace()) for a in 'XYZ'})
            loads.append(load)
            return load
        analysis = SimpleNamespace(IAnalysisSettings=SimpleNamespace(), AddFixedSupport=new_load,
                                   AddForce=new_load, Solution=Mock())
        model = SimpleNamespace(Mesh=SimpleNamespace(), AddStaticStructuralAnalysis=lambda: analysis)
        body = SimpleNamespace()
        ctx = SimpleNamespace(bodies=[body], conditions=self.workspace.get(self.mid)['boundaryConditions'],
                              record=Mock(), selection=lambda keys: ['mapped:' + k for k in keys])
        # Deliberately no mesh/solve methods: exporting must only build setup.
        exec(program['code'], {'ctx': ctx, 'Model': model, 'Quantity': lambda value, unit: (value, unit),
                             'WeakSpringsType': SimpleNamespace(Off='Off'),
                             'ElementOrder': SimpleNamespace(Quadratic='Quadratic'),
                             'LoadDefineBy': SimpleNamespace(Components='Components')})
        self.assertEqual(body.Material, 'Structural Steel')
        self.assertEqual(model.Mesh.ElementSize, (3.0, 'mm'))
        self.assertFalse(analysis.IAnalysisSettings.LargeDeflection)
        self.assertEqual(len(loads), 2)
        self.assertEqual(loads[1].XComponent.Output.DiscreteValues, [(10, 'N')])
        self.assertTrue(all(load.Location[0].startswith('mapped:') for load in loads))

    def test_cached_export_tracks_setup_but_not_camera_selection(self):
        first = self.export()
        self.session.selected = 'different selection'
        self.session.revision += 1
        self.assertEqual(first, self.export())
        self.assertEqual(self.runner.call_count, 1)
        condition = self.workspace.get(self.mid)['boundaryConditions'][1]
        self.service.apply(self.sid, 'apply_condition', {'model_id': self.mid,
            'revision': self.session.revision, 'record_id': condition['id'],
            'face_key': condition['faceKey'], 'kind': 'force', 'values': {'x': 25, 'y': 0, 'z': 0}})
        self.assertNotEqual(first, self.export())
        self.assertEqual(self.runner.call_count, 2)

    def test_generated_project_is_preserved_and_missing_or_stale_project_is_not_rebuilt(self):
        self.session.result = self.make_export()
        self.session.program_attempts = [{'status': 'succeeded'}]
        path = self.export()
        self.runner.assert_not_called()
        self.assertEqual(path.read_bytes(), b'native-test-fixture')
        self.session.result = None
        with self.assertRaisesRegex(ValueError, 'Prepare the current analysis'):
            self.export()
        self.runner.assert_not_called()

    def test_busy_revision_failure_and_missing_assumptions(self):
        with self.assertRaises(ValueError):
            export_mechanical(self.service, self.sid, 'other-model', self.session.revision)
        with self.assertRaises(ValueError):
            export_mechanical(self.service, self.sid, self.mid, -1)
        self.session.busy = True
        with self.assertRaises(ValueError):
            self.export()
        self.session.busy = False
        self.session.material = None
        with self.assertRaisesRegex(ValueError, 'Confirm a simulation setup'):
            self.export()
        self.session.material = 'Structural Steel'
        self.runner.side_effect = RuntimeError('worker unavailable')
        with self.assertRaisesRegex(RuntimeError, 'worker unavailable'):
            self.export()
        self.assertFalse(self.session.running)
        self.assertFalse(self.session.exporting)
        self.assertIsNone(self.session.mechanical_export)

    def test_partial_setup_does_not_require_a_load_and_raw_cad_can_be_exported(self):
        project = self.workspace.get(self.mid)
        for record in project['boundaryConditions'][1:]:
            self.workspace.delete_annotation(self.mid, 'boundaryConditions', record['id'], True)
        self.export()
        for record in self.workspace.get(self.mid)['boundaryConditions']:
            self.workspace.delete_annotation(self.mid, 'boundaryConditions', record['id'], True)
        self.session.material = None
        program = setup_program(self.session, [])
        self.assertNotIn('AddStaticStructuralAnalysis', program['code'])
        validate_program(program)

    def test_endpoint_downloads_native_attachment_and_scopes_it_to_session(self):
        server = FastAPI()
        install_studio(server, self.service)
        with TestClient(server) as client:
            base = '/api/studio/sessions/' + self.sid
            response = client.post(base + '/export-mechanical', json={'model_id': self.mid,
                                                                      'revision': self.session.revision})
            self.assertEqual(response.status_code, 200, response.text)
            exported = response.json()
            download = client.get(exported['url'])
            self.assertEqual(download.content, b'native-test-fixture')
            self.assertIn('attachment', download.headers['content-disposition'])
            self.assertIn('.mechdat', download.headers['content-disposition'])
            other = client.post('/api/studio/sessions').json()['context']['sessionId']
            self.assertEqual(client.get(exported['url'].replace(self.sid, other)).status_code, 404)

    def test_failed_job_never_advertises_native_download(self):
        result = self.make_export()
        self.assertNotIn('mechanicalFile', result_files(result['directory'], {'status': 'failed'}))

    def test_both_exports_disabled_until_setup_and_solved_requires_real_archive(self):
        self.session.material = None
        self.assertFalse(any(x['enabled'] for x in export_options(self.service, self.session).values()))
        self.session.material = 'Structural Steel'
        options = export_options(self.service, self.session)
        self.assertTrue(options['setup']['enabled'])
        self.assertFalse(options['solved']['enabled'])
        with self.assertRaisesRegex(ValueError, 'successful simulation'):
            export_mechanical(self.service, self.sid, self.mid, self.session.revision, 'solved')
        result = self.make_export()
        archive = result['directory'] / 'results/simulation.mechpz'
        archive.write_bytes(b'native-solved-archive-test-fixture')
        report = dict(result['report'], nativeArchive={'file': archive.name, 'includesResults': True})
        self.session.result = result_files(result['directory'], report)
        self.assertTrue(export_options(self.service, self.session)['solved']['enabled'])
        self.assertEqual(export_mechanical(self.service, self.sid, self.mid, self.session.revision, 'solved'), archive)
        self.runner.assert_not_called()
        archive.unlink()
        self.assertFalse(export_options(self.service, self.session)['solved']['enabled'])
