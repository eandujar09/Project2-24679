"""Deploy the authenticated demo to the existing Windows OpenCode machine.

The VM needs Python 3.12 and a dedicated %LOCALAPPDATA%/Project2Studio/.venv
with requirements-gradio.txt installed. Build both frontends before deploying.
No GitHub credentials, local CAD database, or old chat/results are transferred.
"""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mechanical.opencode_connection import OpenCodeConnection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / '.env.local.json')
    parser.add_argument('--port', type=int, default=7860)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Choose an unprivileged TCP port (1024–65535).')
    settings = json.loads(args.config.read_text())
    for key, value in settings.items():
        os.environ.setdefault(key, str(value))
    connection = OpenCodeConnection.from_environment()
    login = json.loads(Path(os.environ.get('OPENCODE_CONFIG', ROOT / '.env.opencode.json')).read_text())
    host = urlsplit(connection.host).hostname
    from gradio_app.hosting import hosting_settings
    hosting_settings(host, os.environ.get('OPENCODE_CONFIG', ROOT / '.env.opencode.json'))

    # Git objects avoid copying environments and local data; overlay only source
    # changes recognized by Git, including newly staged source before a commit.
    source = subprocess.check_output(['git', 'archive', '--format=zip', 'HEAD'], cwd=ROOT)
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        entries = {name: archive.read(name) for name in archive.namelist() if not name.endswith('/')}
    changed = subprocess.check_output(['git', 'diff', '--name-only', 'HEAD', '-z'], cwd=ROOT).decode().split('\0')
    for name in filter(None, changed):
        path = ROOT / name
        if path.is_file():
            entries[name] = path.read_bytes()
        else:
            entries.pop(name, None)
    for directory in ('gradio_app/static', 'gradio_app/studio_static'):
        folder = ROOT / directory
        if not folder.is_dir():
            raise ValueError('Build both frontends before deploying.')
        for path in folder.rglob('*'):
            if path.is_file():
                entries[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    entries['.env.opencode.json'] = json.dumps(login).encode()
    # Absolute paths are assigned by the bootstrap on the Windows machine.
    settings.pop('OPENCODE_CONFIG', None)
    settings.pop('STEP_GRADIO_DATA', None)
    entries['.env.local.json'] = json.dumps(settings).encode()
    entries['.env.host.json'] = json.dumps({'host': host, 'port': args.port}).encode()
    package = io.BytesIO()
    with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    remote_package = '.env.studio-deploy-' + uuid.uuid4().hex + '.zip'
    connection.api.write_file(remote_package, package.getvalue())
    bootstrap = r'''
import datetime,json,os,pathlib,socket,subprocess,sys,zipfile
root=pathlib.Path(os.environ['LOCALAPPDATA'])/'Project2Studio'
python=root/'.venv/Scripts/python.exe'
if not python.is_file():raise RuntimeError('Install a dedicated Studio Python environment first.')
package=pathlib.Path.cwd()/sys.argv[1]
with zipfile.ZipFile(package) as archive:
 host=json.loads(archive.read('.env.host.json'))
 with socket.socket() as sock:
  sock.settimeout(1)
  if sock.connect_ex((host['host'],host['port']))==0:
   raise RuntimeError('The demo port is already in use. Stop the existing demo before redeploying.')
 for name in archive.namelist():
  p=pathlib.PurePosixPath(name)
  if p.is_absolute() or '..' in p.parts or chr(92) in name or ':' in name:raise ValueError('Invalid package path')
 archive.extractall(root)
package.unlink()
settings=json.loads((root/'.env.local.json').read_text())
settings['OPENCODE_CONFIG']=str(root/'.env.opencode.json')
settings['STEP_GRADIO_DATA']=str(root/'gradio-data')
(root/'.env.local.json').write_text(json.dumps(settings,indent=2))
subprocess.run([str(python),str(root/'scripts/install_vm_startup.py')],check=True)
args=[str(python),'-u',str(root/'scripts/run_vm.py'),'--host',host['host'],'--port',str(host['port']),
      '--auth-config',str(root/'.env.opencode.json'),'--log-file',str(root/'studio-runtime/server.log')]
flags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP
try:
 process=subprocess.Popen(args,cwd=root,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL,creationflags=flags|subprocess.CREATE_BREAKAWAY_FROM_JOB)
except OSError:
 process=subprocess.Popen(args,cwd=root,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL,creationflags=flags)
state={'pid':process.pid,'root':str(root),'url':'http://'+host['host']+':'+str(host['port']),
       'startedAt':datetime.datetime.now(datetime.timezone.utc).isoformat()}
print(json.dumps(state))
'''
    wrapped = "import base64;exec(base64.b64decode('" + base64.b64encode(bootstrap.encode()).decode() + "'))"
    info = connection.api.start_shell(connection.python_command(['-c', wrapped, remote_package]), 40)
    connection.api.wait_shell(info, 45)
    print(connection.api.shell_output(info['id']))


if __name__ == '__main__':
    main()
