"""Inspect or recover a previously submitted job after a lost connection."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gradio_app.remote import recover_job
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("record", help="Path to the saved remote-job.json")
parser.add_argument("--fetch", action="store_true", help="Download completed artifacts instead of just reporting status")
args = parser.parse_args()
print(json.dumps(recover_job(args.record, args.fetch), indent=2))
