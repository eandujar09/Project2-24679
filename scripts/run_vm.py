"""Run the same configured app on Windows; accepts --host, --port, --auth-config."""
from pathlib import Path
import argparse
import datetime
import json
import os
import runpy
import sys

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--log-file')
parser.add_argument('--host', default='127.0.0.1')
parser.add_argument('--port', type=int, default=7860)
options, remaining = parser.parse_known_args()
sys.argv = [sys.argv[0], '--host', options.host, '--port', str(options.port), *remaining]
if options.log_file:
    path = Path(options.log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = path.open('a', encoding='utf-8', buffering=1)
root = Path(__file__).resolve().parents[1]
(root / '.env.host-state.json').write_text(json.dumps({
    'pid': os.getpid(), 'root': str(root), 'url': f'http://{options.host}:{options.port}',
    'startedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
}, indent=2))
runpy.run_path(str(Path(__file__).with_name('run_mac.py')), run_name='__main__')
