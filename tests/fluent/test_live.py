"""Opt-in licensed Fluent smoke test using a synthetic rectangular fluid channel.

Set FLUENT_TEST_PYTHON to the dedicated worker interpreter. Never uses user CAD.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
from gradio_app.geometry import read_step
from fluent.contract import UNITS, validate_program
from mechanical.execution import execute_request, archive_run


@unittest.skipUnless(os.environ.get('FLUENT_TEST_PYTHON'), 'Set FLUENT_TEST_PYTHON for a licensed Fluent test.')
class LiveFluentTests(unittest.TestCase):
    def test_cad_mesh_boundary_mapping_and_measured_flow(self):
        parent = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'Temp' / 'opencode'
        parent.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix='studio-fluent-live-', dir=parent))
        source = root / 'channel.step'
        writer = STEPControl_Writer()
        writer.Transfer(BRepPrimAPI_MakeBox(40, 10, 10).Shape(), STEPControl_AsIs)
        writer.Write(str(source))
        _, faces = read_step(source)
        mid = hashlib.sha256(source.read_bytes()).hexdigest()
        conditions = []
        for face in faces:
            x = face['centroidMm'][0]
            kind, values = ('velocity_inlet', dict(x=0.01,y=0,z=0)) if abs(x) < 1e-6 else ('pressure_outlet', {'gauge_pressure':0}) if abs(x-40) < 1e-6 else ('wall', {})
            conditions.append(dict(id=str(face['index']), modelId=mid, faceKey=face['key'], type=kind, values=values))
        program = dict(title='Synthetic fluid channel smoke test', objective='Verify real CAD-to-Fluent meshing, scoping, residuals, mass balance and native exports.',
                       code=(Path(__file__).resolve().parents[2]/'examples/fluent-channel.py').read_text(encoding='utf-8'))
        program['sha256'] = validate_program(program)
        request = dict(schemaVersion=3, solver='fluent', executionMode='agent-authored-v2', modelId=mid, stepFile=str(source),
                       faceMapping='python-ocp-v1', units=UNITS, sourceFaces=faces, selectedFace=None,
                       boundaryConditions=conditions, program=program,
                       analysis=dict(domain='fluid-volume', regime='steady-laminar-incompressible', density=1,
                           dynamic_viscosity=0.001, operating_pressure=101325, mesh_size_mm=2.5,
                           max_iterations=200, residual_tolerance=1e-5, mass_imbalance_tolerance=0.01),
                       settings=dict(fluentVersion=261,solverCores=1,maxCells=32000))
        print('Fluent live-test artifacts: ' + str(root), flush=True)
        report = execute_request(request, root, os.environ['FLUENT_TEST_PYTHON'], 900)
        archive_run(root)
        self.assertEqual(report['status'], 'succeeded', json.dumps(report, indent=2)[-12000:])
        self.assertTrue(report['converged'])
        self.assertEqual(len(report['geometry']['faceZones']), 6)
        self.assertLessEqual(report['mesh']['cells'], 32000)
        self.assertTrue((root/'results'/'case.cas.h5').is_file())
        self.assertTrue((root/'results'/'case.dat.h5').is_file())
        self.assertEqual(len(report['images']), 2)


if __name__ == '__main__':
    unittest.main()
