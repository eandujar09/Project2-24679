"""Native result images through the isolated, post-only MCP adapter; never solve."""
import asyncio
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def configured():
    return bool(os.environ.get('FLUENT_POST_PYTHON') and os.environ.get('FLUENT_POST_SERVER'))


def enrich_result(result):
    """Best-effort graphics after normal execution OR recovery, never submission."""
    report = result['report']
    if report.get('solver') != 'fluent' or report.get('status') != 'succeeded' or not report.get('converged'):
        return result
    try:
        return render_result(result)
    except Exception as exc:
        if report.get('nativePostprocessing', {}).get('status') != 'unknown':
            report['nativePostprocessing'] = {'status':'failed','error':str(exc),'solverRerun':False}
        return result


def render_result(result):
    """Optional enrichment: a graphics failure must never invalidate a verified solve."""
    report = result['report']
    if (report.get('solver') != 'fluent' or report.get('status') != 'succeeded'
            or not report.get('converged') or not any(r.get('status') == 'Done' for r in report.get('verifiedSolves', []))):
        raise ValueError('Native postprocessing requires a completed, converged Fluent solve; no simulation will be submitted.')
    if report.get('nativePostprocessing', {}).get('status') == 'succeeded':
        return result
    if report.get('nativePostprocessing', {}).get('status') == 'unknown':
        raise ValueError('The previous postprocessing session has uncertain status. Confirm it is closed before retrying native graphics; do not rerun the solve.')
    if not configured():
        return result
    directory = Path(result['directory']).resolve()
    output = directory/'results'
    try:
        request_file = next((p for p in (directory/'request.json', directory/'local-request.json') if p.is_file()), None)
        if request_file is None:
            raise ValueError('The saved input snapshot is missing.')
        request = json.loads(request_file.read_text())
        if request.get('modelId') != report.get('modelId') or hashlib.sha256((output/'source.step').read_bytes()).hexdigest() != report['modelId']:
            raise ValueError('Saved result CAD identity does not match its request/report.')
        mapping = json.loads((output/'face-mapping.json').read_text())['faceZones']
        if set(mapping) != {f['key'] for f in request['sourceFaces']} or len(set(mapping.values())) != len(mapping):
            raise ValueError('Saved verified face mapping is incomplete or ambiguous.')
        python, server = os.environ['FLUENT_POST_PYTHON'], os.environ['FLUENT_POST_SERVER']
        if not Path(python).is_file() or not Path(server).is_file():
            raise ValueError('The configured native-post interpreter/server is missing.')
        keep = {'SYSTEMROOT','WINDIR','PATH','PATHEXT','TEMP','TMP','USERPROFILE','HOME','APPDATA','LOCALAPPDATA','AWP_ROOT261'}
        env = {k:v for k,v in os.environ.items() if k.upper() in keep}
        env.update(PYTHONPATH=str(ROOT), PYTHONIOENCODING='utf-8')
        payload = {'server':server, 'case':str(output/'case.cas.h5'), 'output':str(output), 'surfaces':list(mapping.values())}
        child = subprocess.run([python, '-m', 'fluent.postprocessing'], input=json.dumps(payload),
            capture_output=True, text=True, encoding='utf-8', env=env, cwd=ROOT, timeout=300)
        if child.returncode:
            raise ValueError('Native Fluent postprocessing failed; the converged case/data are retained. '+child.stderr[-1800:])
        images = json.loads(child.stdout)['images']
        for item in images:
            name = item['file']
            if name not in ('native-pressure.png','native-velocity.png') or not (output/name).is_file() or not (output/name).stat().st_size:
                raise ValueError('Native MCP image missing or unexpected.')
        existing = [i for i in report.get('images', []) if i.get('file') not in {v['file'] for v in images}]
        # Native Fluent pictures first; extracted Matplotlib plots remain available.
        report['images'] = images + existing
        report['nativePostprocessing'] = {'status':'succeeded','renderer':'fluent-post MCP',
            'scope':'all verified CAD boundary surfaces, not internal flow slices', 'solverRerun':False}
    except subprocess.TimeoutExpired:
        report['nativePostprocessing'] = {'status':'unknown','error':'Native graphics timed out; do not retry until the post session/worker lock is confirmed closed. The converged flow result is unchanged.','solverRerun':False}
    except Exception as exc:
        report['nativePostprocessing'] = {'status':'unknown' if 'uncertain' in str(exc).lower() else 'failed','error':str(exc), 'solverRerun':False}
    from mechanical.contract import write_json
    from mechanical.execution import archive_run, result_files
    write_json(directory/'report.json', report)
    write_json(output/'report.json', report)
    archive_run(directory)
    return result_files(directory, report)


async def render(payload):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=sys.executable, args=[payload['server']], env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=180)) as client:
            await client.initialize()
            async def call(name, args):
                response = await client.call_tool(name, args)
                if response.isError:
                    raise ValueError('Native MCP '+name+' failed.')
                return response
            opened = await call('open_model', {'file_path':payload['case'], 'processor_count':1})
            data = opened.structuredContent or json.loads(next(c.text for c in opened.content if c.type == 'text'))
            if not data.get('success'):
                raise ValueError(data.get('message', 'Could not open saved case/data.'))
            sid, images = data['session_id'], []
            try:
                for label, field, unit in [('pressure','pressure','Pa gauge'),('velocity','velocity-magnitude','m/s')]:
                    name = 'studio-native-'+label
                    await call('create_contour', {'session_id':sid, 'name':name, 'field':field, 'surfaces':payload['surfaces']})
                    common = {'session_id':sid, 'output_dir':payload['output']}
                    await call('set_display_target', dict(common, target=name))
                    response = await call('view_canonical', dict(common, name='isometric'))
                    image = next((c for c in response.content if c.type == 'image' and c.mimeType == 'image/png'), None)
                    if image is None:
                        raise ValueError('Native renderer did not return PNG image content.')
                    import base64
                    filename = 'native-'+label+'.png'
                    Path(payload['output'], filename).write_bytes(base64.b64decode(image.data, validate=True))
                    images.append({'file':filename, 'label':f'Native Fluent {label} ({unit}) · CAD boundary surfaces'})
            finally:
                closed = await call('close_model', {'session_id':sid})
                status = closed.structuredContent or json.loads(next(c.text for c in closed.content if c.type=='text'))
                if not status.get('success'):
                    raise ValueError('Native post session close is uncertain; do not rerun the flow solve.')
            return {'images':images}


if __name__ == '__main__':
    print(json.dumps(asyncio.run(render(json.load(sys.stdin)))))
