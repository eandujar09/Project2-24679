#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
if [[ ! -x .venv-gradio/bin/python ]]; then
  print 'Run scripts/setup-mac.sh once to install the local app.'
  exit 1
fi
exec .venv-gradio/bin/python scripts/run_mac.py
