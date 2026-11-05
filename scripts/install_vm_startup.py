"""Start the private demo when the current Windows user signs in."""
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    if sys.platform != 'win32':
        raise SystemExit('Run this script with the dedicated Studio Python on Windows.')
    from win32com.client import Dispatch

    root = Path(__file__).resolve().parents[1]
    host = json.loads((root / '.env.host.json').read_text())
    python = root / '.venv/Scripts/pythonw.exe'
    if not python.is_file():
        raise SystemExit('The dedicated Studio Python environment is missing.')
    startup = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Startup'
    startup.mkdir(parents=True, exist_ok=True)
    path = startup / 'Project2 Simulation Studio.lnk'
    link = Dispatch('WScript.Shell').CreateShortcut(str(path))
    link.TargetPath = str(python)
    link.Arguments = subprocess.list2cmdline([
        str(root / 'scripts/run_vm.py'), '--host', host['host'], '--port', str(host['port']),
        '--auth-config', str(root / '.env.opencode.json'),
        '--log-file', str(root / 'studio-runtime/server.log'),
    ])
    link.WorkingDirectory = str(root)
    link.Description = 'Private Simulation Studio demo on Tailscale'
    link.WindowStyle = 7
    link.Save()
    print(json.dumps({'startupShortcut': str(path), 'startsOn': 'current Windows user sign-in'}))


if __name__ == '__main__':
    main()
