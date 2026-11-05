"""Deploy only the simulation worker through OpenCode's API or optional SSH."""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
import base64

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mechanical.ssh_connection import SSHConnection
from mechanical.opencode_connection import OpenCodeConnection

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--config", default=str(ROOT / ".env.local.json"))
args = parser.parse_args()
for key, value in json.loads(Path(args.config).read_text()).items():
    if key.startswith("MECHANICAL_") or key == "OPENCODE_CONFIG":
        os.environ.setdefault(key, str(value))
is_api = os.environ.get("MECHANICAL_TRANSPORT", "opencode") == "opencode"
connection = OpenCodeConnection.from_environment() if is_api else SSHConnection.from_environment()
buffer = io.BytesIO()
with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted((ROOT / "mechanical").glob("*.py")):
        archive.write(path, path.relative_to(ROOT).as_posix())
    for name in ("scripts/ssh-worker.py", "scripts/api-worker.py", "requirements-mechanical.txt"):
        archive.write(ROOT / name, name)
if is_api:
    active = connection.api.json("/api/shell")["data"]
    if any(item.get("metadata", {}).get("project") == "Project2-24679" for item in active):
        sys.exit("A Project2 command is still running. Deploy after it finishes.")
    import uuid
    package = "worker-package/" + uuid.uuid4().hex + ".zip"
    connection.api.write_file(package, buffer.getvalue())
    bootstrap = '''import pathlib,sys,zipfile
root=pathlib.Path(sys.argv[1]); package=root/sys.argv[2]
with zipfile.ZipFile(package) as archive:
 for item in archive.infolist():
  p=pathlib.PurePosixPath(item.filename)
  if p.is_absolute() or '..' in p.parts or chr(92) in item.filename: raise ValueError('Invalid worker archive')
 archive.extractall(root)
package.unlink()
print('Worker source deployed')
'''
    info = connection.api.start_shell(connection.python_command(["-c", bootstrap, connection.directory, package]), 30)
    connection.api.wait_shell(info, 40)
    print(connection.api.shell_output(info["id"]).strip())
    print(json.dumps(connection.check(), indent=2))
    sys.exit(0)
# Only this worker's source is deployed; no CAD data or environment changes.
bootstrap = '''import base64,io,pathlib,sys,zipfile
root=pathlib.Path(sys.argv[1]); root.mkdir(parents=True,exist_ok=True)
archive=zipfile.ZipFile(io.BytesIO(base64.b64decode(sys.stdin.buffer.read())))
for item in archive.infolist():
 p=pathlib.PurePosixPath(item.filename)
 if p.is_absolute() or '..' in p.parts or chr(92) in item.filename: raise ValueError('Invalid worker archive')
for item in archive.infolist():
 target=root/item.filename; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(archive.read(item))
print('Worker deployed to '+str(root))
'''
result = subprocess.run(connection.python_command(["-c", bootstrap, connection.directory]),
                        input=base64.b64encode(buffer.getvalue()), capture_output=True, timeout=60)
if result.returncode:
    sys.exit(result.stderr.decode(errors="replace"))
print(result.stdout.decode(errors="replace").strip())
print(json.dumps(connection.check(), indent=2))
