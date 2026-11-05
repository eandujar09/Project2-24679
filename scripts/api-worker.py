"""Absolute-path entry point used by the OpenCode shell API."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mechanical.ssh_worker import main

if __name__ == "__main__":
    sys.exit(main())
