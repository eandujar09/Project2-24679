"""Bound model-visible data without truncating the saved authoritative artifacts."""
import json


def bounded(value, max_chars=16000):
    def visit(item, depth=0):
        if isinstance(item, str):
            return item if len(item) <= 3000 else item[:1000] + '\n[truncated; full text retained in artifacts]\n' + item[-1800:]
        if depth > 8:
            return '[nested data omitted; retained in artifacts]'
        if isinstance(item, dict):
            out = {}
            for key, val in list(item.items())[:60]:
                if key == 'exampleCode' and isinstance(val, str) and len(val) <= 12000:
                    out[key] = val
                elif key in ('verticesMm', 'edges', 'samples', 'vertices', 'triangles', 'base64_data'):
                    out[key] = {'omittedFromChat': True, 'count': len(val) if hasattr(val, '__len__') else None}
                else:
                    out[key] = visit(val, depth + 1)
            return out
        if isinstance(item, (list, tuple)):
            if len(item) <= 12:
                return [visit(v, depth + 1) for v in item]
            return {'count': len(item), 'truncated': True,
                    'first': [visit(v, depth + 1) for v in item[:3]],
                    'last': [visit(v, depth + 1) for v in item[-5:]]}
        return item
    result = visit(value)
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return result
    # Remain valid JSON, mark the omission, and retain the end (often diagnostics).
    return {'truncated': True, 'originalSummaryChars': len(text),
            'summaryStart': text[:max_chars // 3], 'summaryEnd': text[-max_chars // 2:],
            'note': 'Full data remains in saved artifacts; narrow the next inspection query.'}


def result_summary(report):
    keys = ('status', 'kind', 'solver', 'converged', 'title', 'modelId', 'jobId',
            'results', 'mesh', 'messages', 'error', 'limitations', 'tables', 'metrics',
            'verifiedSolves', 'stdout', 'traceback', 'errorStage', 'programSHA256', 'gravityLoads',
            'nativePostprocessing', 'images')
    out = {key: bounded(report.get(key), 6000) for key in keys}
    geometry = report.get('geometry') or {}
    out['geometry'] = {key: geometry[key] for key in
        ('cadVolumeMm3', 'lengthUnit', 'mappingStatus', 'importMethod') if key in geometry}
    out['geometry']['faceCount'] = len(geometry.get('faces', []))
    out['fullDiagnosticsInArtifacts'] = True
    return out
