"""Gradio HTML bridge to the original Three.js viewer; no separate Vite server."""

import json
import os
from pathlib import Path
import subprocess
from urllib.parse import quote

import gradio as gr

STATIC = Path(__file__).resolve().parent / "static"
ROOT = STATIC.parent.parent


def ensure_viewer_bundle():
    bundle = STATIC / "viewer.js"
    sources = [ROOT / "vite.gradio.config.js", ROOT / "package.json"]
    for directory in ("src/gradio", "src/viewer", "src/cad", "src/boundaries"):
        sources.extend((ROOT / directory).glob("*.*"))
    if bundle.exists() and (STATIC / "gradio.css").exists() and all(
            path.stat().st_mtime <= bundle.stat().st_mtime for path in sources):
        return
    npm = "npm.cmd" if os.name == "nt" else "npm"
    try:
        subprocess.run([npm, "run", "build:gradio"], cwd=ROOT, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("Build the CAD viewer with `npm.cmd install` and `npm.cmd run build:gradio` first.") from exc


def file_url(path):
    return f"/gradio_api/file={quote(path.as_posix(), safe='/:')}"


def cad_viewer():
    ensure_viewer_bundle()
    module = json.dumps(file_url(STATIC / "viewer.js"))
    return gr.HTML(
        value="", html_template='<div class="python-cad-viewer" aria-label="Interactive CAD preview"></div>',
        js_on_load=f"""
            import({module}).then(module => module.mount(element, props, trigger, watch))
                .catch(error => {{ element.textContent = 'Could not load CAD viewer: ' + error.message; }});
            // The mount function emits trigger('select', {{modelId, faceKey}}).
        """,
        head=f'<link rel="stylesheet" href="{file_url(STATIC / "gradio.css")}">',
        elem_id="python-cad-preview", apply_default_css=False,
    )
