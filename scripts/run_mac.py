"""Load private local settings, then run Simulation Studio on this Mac."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
config = ROOT / ".env.local.json"
if config.is_file():
    for key, value in json.loads(config.read_text()).items():
        if key not in {"CAD_CHAT_MODEL", "CAD_CHAT_PROVIDER_ID", "MECHANICAL_TRANSPORT", "OPENCODE_CONFIG", "MECHANICAL_SSH_HOST", "MECHANICAL_REMOTE_DIR", "MECHANICAL_REMOTE_PYTHON", "MECHANICAL_REMOTE_PLATFORM", "MECHANICAL_PYTHON", "STEP_GRADIO_DATA", "FLUENT_REMOTE_DIR", "FLUENT_REMOTE_PYTHON", "FLUENT_MCP_PYTHON", "FLUENT_MCP_API_OBJECTS_PATH", "FLUENT_POST_PYTHON", "FLUENT_POST_SERVER"}:
            raise ValueError("Unknown local setting: " + key)
        os.environ.setdefault(key, str(value))

from gradio_app.app import main
main()
