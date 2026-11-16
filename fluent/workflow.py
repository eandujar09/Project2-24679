"""Read-only preparation guidance, never a hidden simulation template."""
from pathlib import Path
from .contract import KINDS


def review(project):
    faces = {f['key'] for f in project['faces']}
    rows = [r for r in project['boundaryConditions'] if r['type'] in KINDS]
    assigned = {r['faceKey'] for r in rows}
    analysis = project.get('fluentAnalysis')
    domain = project.get('fluidDomain')
    missing = []
    if not domain or domain.get('status') != 'ready':
        missing.append('Identify/prepare the actual fluid volume.')
    if not analysis:
        missing.append('Establish the intended physics/materials/numerics; saved assumptions are optional for custom authored jobs.')
    if faces - assigned:
        missing.append('Specify conditions for unassigned faces; never assume every remaining face is a wall.')
    kinds = {r['type'] for r in rows}
    if not {'velocity_inlet', 'pressure_outlet'} <= kinds:
        missing.append('The saved-water example needs a velocity inlet and pressure outlet; custom authored physics may differ.')
    code = (Path(__file__).resolve().parent.parent/'examples/fluent-native-steady-water.py').read_text()
    return {'solverLaunched': False, 'readOnly': True, 'missingInformation': missing,
            'unassignedFaceKeys': sorted(faces-assigned), 'conditionCount': len(rows),
            'savedAnalysis': analysis, 'exampleCode': code,
            'exampleScope': 'Reference only: adapt the authored code to approved physics, every mapped condition and desired outputs. Never execute automatically or silently apply water/laminar/numerical assumptions.',
            'workingMeshStrategy': 'Native STEP; OneZonePer=face in import AND surface generation; retain CAD curvature. 6-degree curvature/polyhedral controls worked on the saved-water model, not a universal mesh guarantee.',
            'workingStabilization': 'For the saved steady laminar water case only: coupled explicit pressure/momentum relaxation 0.2/0.5, high-order relaxation 0.25, pseudo-time scale 0.1. Propose numerical choices as part of exact code; do not loosen acceptance criteria.',
            'limits': {'maxCells':32000, 'cores':1, 'deadlineSeconds':900, 'maxRequestedIterations':2000},
            'nextStep': 'Ask only for missing intent, then check worker once, discover unfamiliar APIs, validate the snippet and full authored code, and follow current execution-confirmation mode.'}
