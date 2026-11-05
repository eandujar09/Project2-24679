"""Execute model-authored PyMechanical code in a fresh, time-limited worker job.

This is a separate process, not a security sandbox. It uses the worker account's
permissions. There is no predefined analysis, material, mesh or load setup here.
"""
import argparse
import contextlib
import csv
import hashlib
import importlib.metadata
import io
import json
import math
from pathlib import Path
import re
import shutil
import sys
import time
import traceback

from .contract import validate_request, write_json
from .model_io import import_geometry


class ExecutionContext:
    def __init__(self, app, ns, output, request, report, bodies, mapping, geometry):
        self.app, self.ns, self.output, self.report = app, ns, output, report
        self.bodies, self.face_ids, self.geometry = bodies, mapping, geometry
        self.conditions = request.get('boundaryConditions', [])
        self.selected_face = request.get('selectedFace')
        self.mesh_limit = request['settings']['maxMeshEntities']

    def artifact(self, name):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', name) or '..' in name:
            raise ValueError('Artifacts need a simple filename inside the current job.')
        return str(self.output / name)

    def selection(self, keys):
        if not keys or any(key not in self.face_ids for key in keys):
            raise ValueError('A requested face lacks a verified mapping. Inspect ctx.geometry; never guess clicked-face IDs.')
        selection = self.ns['ExtAPI'].SelectionManager.CreateSelectionInfo(self.ns['SelectionTypeEnum'].GeometryEntities)
        selection.Ids = [self.face_ids[key] for key in keys]
        return selection

    def describe(self, obj):
        result = {'type': str(type(obj)), 'members': [k for k in dir(obj) if not k.startswith('_')][:250]}
        doc = getattr(obj, '__doc__', None)
        if doc:
            result['doc'] = str(doc)[:4000]
        return result

    def mesh_counts(self):
        mesh = self.ns['ExtAPI'].DataModel.MeshDataByName('Global')
        return {'nodes': int(mesh.NodeCount), 'elements': int(mesh.ElementCount)}

    def check_mesh(self):
        counts = self.mesh_counts()
        if min(counts.values()) <= 0:
            raise ValueError('Generate a nonempty mesh before solving.')
        if max(counts.values()) > self.mesh_limit:
            raise ValueError('Mesh has {nodes} nodes / {elements} elements; the worker limit is '.format(**counts)
                             + str(self.mesh_limit) + '. Use a coarser mesh and revise the study.')
        return counts

    def generate_mesh(self):
        self.ns['Model'].Mesh.GenerateMesh()
        counts = self.check_mesh()
        self.report['mesh'] = counts
        print('Generated mesh:', counts, flush=True)
        return counts

    def solve(self, analysis):
        counts = self.check_mesh()
        api = self.ns['ExtAPI']
        config = api.Application.SolveConfigurations['My Computer']
        config.SolveProcessSettings.MaxNumberOfCores = 1
        config.SolveProcessSettings.DistributeSolution = False
        config.SolveProcessSettings.GPUAccelerationDevice = getattr(self.ns['GPUAccelerationDevicesType'], 'None')
        config.SolveProcessSettings.NumberOfGPUDevices = 0
        entry = {'analysisName': str(analysis.Name), 'mesh': counts, 'status': 'running'}
        self.report['verifiedSolves'].append(entry)
        started = time.monotonic()
        try:
            analysis.Solution.Solve(True, config)
            entry['status'] = str(analysis.Solution.Status)
            if entry['status'] != 'Done':
                raise ValueError('Mechanical solve returned ' + entry['status'])
            analysis.Solution.EvaluateAllResults()
            self.report['mesh'] = counts
            print('Verified solve:', entry['analysisName'], entry['status'], counts, flush=True)
            return dict(entry)
        except Exception:
            if entry['status'] == 'running':
                entry['status'] = 'failed'
            raise
        finally:
            entry['elapsedSeconds'] = round(time.monotonic() - started, 3)
            self._solver_logs(analysis, len(self.report['verifiedSolves']))

    def _solver_logs(self, analysis, number):
        try:
            folder = Path(str(analysis.WorkingDir))
            target = self.output / ('solver-logs-' + str(number))
            for source in folder.iterdir():
                if source.is_file() and source.suffix.lower() in ('.err', '.out', '.log', '.txt'):
                    target.mkdir(exist_ok=True)
                    shutil.copy2(source, target / source.name)
        except Exception as exc:
            self.report.setdefault('warnings', []).append('Solver logs: ' + str(exc))

    def capture(self, result, name, label=None):
        if not self.report['verifiedSolves'] or self.report['verifiedSolves'][-1]['status'] != 'Done':
            raise ValueError('A successful ctx.solve is required before exporting simulation results.')
        result.EvaluateAllResults()
        lo, hi = result.Minimum, result.Maximum
        item = {'minimum': float(lo.Value), 'maximum': float(hi.Value), 'unit': str(hi.Unit),
                'label': label or str(result.Name), 'solveIndex': len(self.report['verifiedSolves']) - 1}
        if not all(math.isfinite(item[k]) for k in ('minimum', 'maximum')):
            raise ValueError('Result extrema are not finite: ' + name)
        self.report['results'][name] = item
        result.ExportToTextFile(self.artifact(name + '.txt'))
        result.Activate()
        self.snapshot(name, item['label'])
        return item

    def snapshot(self, name, label=None):
        path = self.artifact(name + '.png')
        graphics = self.ns['ExtAPI'].Graphics
        graphics.Camera.SetSpecificViewOrientation(self.ns['ViewOrientationType'].Iso)
        graphics.Camera.SetFit()
        graphics.ExportImage(path)
        if not Path(path).is_file():
            raise ValueError('Mechanical did not create the image.')
        # Replace a repeated image name rather than showing the same output twice.
        self.report['images'] = [i for i in self.report['images'] if i['file'] != name + '.png']
        self.report['images'].append({'file': name + '.png', 'label': label or name})
        return name + '.png'

    def table(self, name, rows):
        if not isinstance(rows, list) or len(rows) > 1000 or any(not isinstance(row, dict) for row in rows):
            raise ValueError('Tables require at most 1000 dictionary rows.')
        json.dumps(rows, allow_nan=False)
        self.report['tables'][name] = rows
        write_json(self.artifact(name + '.json'), rows)
        if rows:
            fields = list(dict.fromkeys(k for row in rows for k in row))
            with open(self.artifact(name + '.csv'), 'w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
        return rows

    def record(self, name, value, unit=None):
        json.dumps(value, allow_nan=False)
        self.report['metrics'][name] = {'value': value, 'unit': unit}
        return value

    def save_project(self, name='model.mechdb'):
        if not name.endswith('.mechdb'):
            raise ValueError('Use a .mechdb project filename.')
        self.app.save(self.artifact(name))
        return name


class Tee(io.TextIOBase):
    def __init__(self, stream, file):
        self.stream, self.file = stream, file
    def write(self, text):
        self.stream.write(text)
        self.file.write(text)
        return len(text)
    def flush(self):
        self.stream.flush()
        self.file.flush()


def run(request_path, output):
    request_path, output = Path(request_path).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    request = json.loads(request_path.read_text(encoding='utf-8'))
    program = request['program']
    report = {'status': 'failed', 'kind': 'generated-python', 'modelId': request['modelId'],
              'title': program['title'], 'objective': program['objective'],
              'programSHA256': hashlib.sha256(program['code'].encode()).hexdigest(),
              'verifiedSolves': [], 'results': {}, 'tables': {}, 'metrics': {}, 'images': [],
              'limitations': ['Model-authored analysis code; engineering assumptions and convergence require review.',
                              'Fresh Mechanical job, one CPU, maximum 32000 nodes/elements per solve; 15 minute job timeout.']}
    app, context = None, None
    stage = 'initialization'
    code_path = output / 'agent.py'
    code_path.write_text(program['code'], encoding='utf-8')
    with (output / 'stdout.txt').open('w', encoding='utf-8') as stream:
        with contextlib.redirect_stdout(Tee(sys.stdout, stream)), contextlib.redirect_stderr(Tee(sys.stderr, stream)):
            try:
                validate_request(request)
                shutil.copy2(request['stepFile'], output / 'source.step')
                shutil.copy2(request_path, output / 'request.json')
                from ansys.mechanical.core import App
                app = App(version=261, private_appdata=True)
                ns = {}
                app.update_globals(ns)
                api = ns['ExtAPI']
                report['mechanicalVersion'] = str(api.Application.WBVersion)
                report['pyMechanicalVersion'] = importlib.metadata.version('ansys-mechanical-core')
                if report['mechanicalVersion'] != '261':
                    raise ValueError('Mechanical version does not match this job.')
                api.Application.ActiveUnitSystem = ns['MechanicalUnitSystem'].StandardNMM
                stage = 'geometry import and mapping'
                bodies, mapping, evidence, geometry = import_geometry(request, output, ns)
                report['geometry'] = geometry
                write_json(output / 'face-mapping.json', evidence)
                context = ExecutionContext(app, ns, output, request, report, bodies, mapping, geometry)
                ns['ctx'] = context
                print('Executing model-authored Python:', program['title'], flush=True)
                stage = 'generated Python'
                exec(compile(program['code'], str(code_path), 'exec'), ns)
                stage = 'project export'
                context.save_project()
                report['status'] = 'succeeded'
            except Exception as exc:
                report['error'] = str(exc)
                report['errorStage'] = stage
                report['traceback'] = traceback.format_exc()[-10000:]
                traceback.print_exc()
                if context is not None:
                    try:
                        context.save_project('failed-attempt.mechdb')
                    except Exception:
                        pass
            finally:
                if app is not None:
                    try:
                        report['messages'] = [{'severity': str(m.Severity), 'text': str(m.DisplayString)}
                                              for m in ns['ExtAPI'].Application.Messages]
                    except Exception:
                        pass
                    app.close()
    report['stdout'] = (output / 'stdout.txt').read_text(encoding='utf-8', errors='replace')[-16000:]
    write_json(output / 'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    report = run(args.request, args.output_dir)
    print(json.dumps(report, allow_nan=False))
    return 0 if report['status'] == 'succeeded' else 1


if __name__ == '__main__':
    sys.exit(main())
