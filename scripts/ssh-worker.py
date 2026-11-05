"""Absolute-path entry point, independent of the SSH session's working directory."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mechanical.ssh_worker import main
try:
    sys.exit(main())
except Exception as exc:
    print(str(exc), file=sys.stderr)
    sys.exit(1)
