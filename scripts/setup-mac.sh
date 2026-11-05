#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")/.."
if command -v uv >/dev/null; then
  uv venv --python 3.12 .venv-gradio
  uv pip install --python .venv-gradio/bin/python -r requirements-gradio.txt
else
  python3.12 -m venv .venv-gradio
  .venv-gradio/bin/python -m pip install -r requirements-gradio.txt
fi
npm ci
npm run build:gradio
npm run build:studio
print 'Setup complete. Open Start Mac App.command to run the app.'
