"""Run with: python -m gradio_app.app"""

import argparse
from functools import wraps
import os
from pathlib import Path

import gradio as gr

from .backend import Workspace
from .viewer import STATIC, cad_viewer
from .simulation import default_python, run_project


def user_errors(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (ValueError, OSError) as exc:
            raise gr.Error(str(exc)) from exc
    return wrapped


def build_app(workspace):
    with gr.Blocks(title="STEP Face Comments · Python", analytics_enabled=False) as app:
        model = gr.State(None)
        gr.Markdown("# STEP Face Comments\nGradio workspace · interactive CAD viewer · Python/OpenCascade backend")
        gr.Markdown(
            "Files are processed and stored **on the Python server**. Click a CAD face or use the dropdown. "
            "Teal = hover; amber = selected; purple = fixed; green = displacement; "
            "coral = force; blue = pressure. Use the Mechanical simulation section below to solve a saved annotation snapshot."
        )
        with gr.Row():
            upload = gr.File(label="Open STEP", file_types=[".step", ".stp"], type="filepath")
            with gr.Column():
                saved = gr.Dropdown(label="Saved projects", choices=workspace.projects())
                with gr.Row():
                    refresh = gr.Button("Refresh project list")
                    reopen = gr.Button("Reopen selected project")
        status = gr.Textbox(label="Project status", interactive=False)
        with gr.Row():
            with gr.Column(scale=2):
                viewer = cad_viewer()
                with gr.Row():
                    face = gr.Dropdown(label="Select whole CAD face", choices=[])
                    clear = gr.Button("Clear face")
                face_info = gr.JSON(label="Selected face metadata (mm, mm²)")
                table = gr.Dataframe(headers=["Kind", "Face", "Text / values", "ID"],
                                     datatype=["str"] * 4, interactive=False, label="All project annotations")
            with gr.Column():
                with gr.Tab("Comments"):
                    comment = gr.Dropdown(label="Choose comment to navigate / edit", choices=[])
                    text = gr.Textbox(label="Comment text", lines=4, max_length=20000)
                    with gr.Row():
                        new_comment = gr.Button("New comment")
                        save_comment = gr.Button("Save comment", variant="primary")
                    confirm_comment = gr.Checkbox(label="Confirm comment deletion")
                    delete_comment = gr.Button("Delete selected comment", variant="stop")
                with gr.Tab("Boundary conditions"):
                    condition = gr.Dropdown(label="Choose condition to navigate / edit", choices=[])
                    kind = gr.Dropdown(label="Condition type", choices=[
                        ("Fixed support (Ux = Uy = Uz = 0)", "fixed"),
                        ("Prescribed displacement (mm)", "displacement"),
                        ("Total face force (N)", "force"), ("Pressure (MPa)", "pressure"),
                    ], value="fixed")
                    gr.Markdown("Vectors use global X/Y/Z. Positive pressure acts inward; negative outward. "
                                "All three displacement components are prescribed, including zeros.")
                    with gr.Row():
                        x = gr.Number(label="X (mm or N)", value=0)
                        y = gr.Number(label="Y (mm or N)", value=0)
                        z = gr.Number(label="Z (mm or N)", value=0)
                    pressure = gr.Number(label="Pressure (MPa)", value=1)
                    gr.Markdown("Only values relevant to the chosen type are used. "
                                "The preview shows whole-face tints, directional arrows, and support glyphs.")
                    with gr.Row():
                        new_condition = gr.Button("New condition")
                        save_condition = gr.Button("Apply to face", variant="primary")
                    confirm_condition = gr.Checkbox(label="Confirm condition deletion")
                    delete_condition = gr.Button("Delete selected condition", variant="stop")
        with gr.Row():
            incoming = gr.File(label="Import annotation JSON (merge)", file_types=[".json"], type="filepath")
            with gr.Column():
                export = gr.Button("Export annotation JSON")
                download = gr.File(label="Download JSON", interactive=False)
        gr.Markdown("Python face keys are importer-specific, **not Ansys Mechanical entity IDs**. "
                    "Browser-app JSON can be read, but its different face keys remain unmapped. "
                    "No automatic topology reassignment is performed.")

        with gr.Accordion("Ansys Mechanical · deterministic static structural simulation", open=False):
            gr.Markdown(
                "Runs **Mechanical 2026 R1 (261)** in a separate Python process using the current model's saved "
                "boundary conditions. Supported scope: **one solid**, Mechanical's **Structural Steel** library material, "
                "linear elastic/small deformation, one load step, quadratic tetrahedra, one CPU core, and **no weak springs**. "
                "Assemblies, contacts, shells, beams, conflicting supports, and ambiguous face mappings are rejected. "
                "The conservative mesh limit is 32,000 nodes/elements. Review the assumptions before solving."
            )
            mechanical_python = gr.Textbox(label="Mechanical Python executable", value=default_python(),
                                           placeholder="Path to Python in your PyMechanical environment")
            element_size = gr.Number(label="Mesh element size (mm)", value=3, minimum=0.001)
            confirm_solve = gr.Checkbox(label="I confirm Structural Steel and the single-solid, small-deformation assumptions for this simulation")
            solve = gr.Button("Run simulation in Mechanical", variant="primary")
            simulation_status = gr.Markdown("No simulation run in this session. Results below belong to their recorded model hash and input snapshot.")
            simulation_results = gr.JSON(label="Simulation report · extrema, units, mesh, mapping, solver messages")
            contours = gr.Gallery(label="Mechanical results · total deformation and von Mises stress", columns=2, object_fit="contain", height="auto")
            simulation_files = gr.File(label="Download simulation artifacts (ZIP includes project, results, inputs, and logs)", file_count="multiple", interactive=False)

        outputs = [model, viewer, face, face_info, comment, condition, table, status,
                   text, kind, x, y, z, pressure, confirm_comment, confirm_condition, saved, download]

        def face_metadata(project, key):
            return next((item for item in project["faces"] if item["key"] == key), None)

        def render(project, selected=None, focus=False):
            keys = {f["key"] for f in project["faces"]}
            rows = []
            choices = {}
            for collection in ("comments", "boundaryConditions"):
                choices[collection] = []
                for item in project[collection]:
                    label = item["faceKey"] if item["faceKey"] in keys else f'Unmapped: {item["faceKey"]}'
                    summary = item["text"] if collection == "comments" else f'{item["type"]}: {item["values"]}'
                    choices[collection].append((f'{label} · {summary[:70]} · {item["id"][:8]}', item["id"]))
                    rows.append(["Comment" if collection == "comments" else item["type"], label, summary, item["id"]])
            unmapped = sum(item["faceKey"] not in keys for collection in ("comments", "boundaryConditions") for item in project[collection])
            return (
                project["id"], workspace.viewer_state(project["id"], selected, focus),
                gr.Dropdown(choices=[(f'Face {f["index"]} · {f["areaMm2"]:.3g} mm²', f["key"]) for f in project["faces"]], value=selected),
                face_metadata(project, selected),
                gr.Dropdown(choices=choices["comments"], value=None),
                gr.Dropdown(choices=choices["boundaryConditions"], value=None), rows,
                f'{project["filename"]} · {len(keys)} faces · {len(project["comments"])} comments · '
                f'{len(project["boundaryConditions"])} conditions · {unmapped} unmapped · saved on Python server',
                "", "fixed", 0, 0, 0, 1, False, False,
                gr.Dropdown(choices=workspace.projects(), value=project["id"]), None,
            )

        @user_errors
        def open_file(path):
            if not path:
                raise ValueError("Choose a STEP file first.")
            return render(workspace.open_step(path))

        @user_errors
        def open_saved(model_id):
            return render(workspace.get(model_id))

        @user_errors
        def select_face(model_id, key):
            return render(workspace.get(model_id), key, focus=bool(key))

        @user_errors
        def pick_face(model_id, event: gr.EventData):
            data = event._data
            if not isinstance(data, dict) or data.get("modelId") != model_id:
                # Ignore a click that was queued before another model replaced it.
                return tuple(gr.skip() for _ in outputs)
            key = data.get("faceKey")
            return render(workspace.get(model_id), key)

        @user_errors
        def navigate(model_id, record_id, collection):
            project = workspace.get(model_id)
            record = next((r for r in project[collection] if r["id"] == record_id), None)
            if record is None:
                return render(project)
            mapped = face_metadata(project, record["faceKey"])
            result = list(render(project, record["faceKey"] if mapped else None, focus=True))
            if not mapped:
                gr.Warning("This annotation's face is unmapped. It can be deleted, but not edited or reassigned.")
            if collection == "comments":
                result[4] = gr.update(value=record_id)
                result[8] = record["text"]
            else:
                result[5] = gr.update(value=record_id)
                result[9] = record["type"]
                result[10:14] = [record["values"].get(axis, 0) for axis in "xyz"] + [record["values"].get("magnitude", 1)]
            return tuple(result)

        @user_errors
        def write_comment(model_id, key, record_id, content):
            return render(workspace.save_annotation(model_id, key, "comments", {"text": content}, record_id), key)

        def navigate_comment(model_id, record_id):
            return navigate(model_id, record_id, "comments")

        def navigate_condition(model_id, record_id):
            return navigate(model_id, record_id, "boundaryConditions")

        @user_errors
        def write_condition(model_id, key, record_id, selected_kind, vx, vy, vz, magnitude):
            values = {"x": vx, "y": vy, "z": vz} if selected_kind in ("force", "displacement") else (
                {"magnitude": magnitude} if selected_kind == "pressure" else {})
            return render(workspace.save_annotation(model_id, key, "boundaryConditions",
                                                    {"type": selected_kind, "values": values}, record_id), key)

        @user_errors
        def remove(model_id, record_id, confirmed, collection):
            return render(workspace.delete_annotation(model_id, collection, record_id, confirmed))

        @user_errors
        def merge(model_id, path):
            if not path:
                raise ValueError("Choose a JSON file first.")
            return render(workspace.import_annotations(model_id, path))

        @user_errors
        def run_simulation(model_id, executable, mesh_size, confirmed, progress=gr.Progress()):
            if not confirmed:
                raise ValueError("Confirm the simulation's material and modeling assumptions first.")
            progress(0.05, desc="Validating annotations and preparing exact CAD face signatures")
            # All project events share this callback's queue lock, so annotations
            # cannot mutate during the snapshot/solve lifecycle in this process.
            progress(0.1, desc="Running Mechanical: import, face mapping, mesh, solve, result export")
            result = run_project(workspace, model_id, executable, mesh_size)
            report, directory = result["report"], result["directory"]
            progress(1.0, desc="Mechanical worker finished")
            succeeded = report["status"] == "succeeded"
            headline = "**Simulation succeeded.**" if succeeded else "**Simulation failed.** " + report.get("error", "See the worker log.")
            headline += f" Model SHA-256: `{report['modelId']}`. Results are a snapshot, not a live update of subsequent annotations."
            labels = ("Total deformation (mm)", "Equivalent von Mises stress (MPa)")
            images = list(zip(result["images"], labels))
            files = [str(directory / name) for name in ("request.json", "report.json", "run.log")]
            if result["archive"]:
                files.insert(0, result["archive"])
            return headline, report, images, files, False

        # A single queue group serializes native STEP work and project mutations.
        event_options = {"concurrency_id": "workspace", "concurrency_limit": 1}
        upload.upload(open_file, upload, outputs, **event_options)
        reopen.click(open_saved, saved, outputs, **event_options)
        refresh.click(lambda: gr.Dropdown(choices=workspace.projects(), value=None), outputs=saved, **event_options)
        face.input(select_face, [model, face], outputs, **event_options)
        viewer.select(pick_face, model, outputs, **event_options)
        clear.click(lambda mid: select_face(mid, None), model, outputs, **event_options)
        comment.input(navigate_comment, [model, comment], outputs, **event_options)
        condition.input(navigate_condition, [model, condition], outputs, **event_options)
        new_comment.click(lambda mid, key: select_face(mid, key), [model, face], outputs, **event_options)
        new_condition.click(lambda mid, key: select_face(mid, key), [model, face], outputs, **event_options)
        save_comment.click(write_comment, [model, face, comment, text], outputs, **event_options)
        save_condition.click(write_condition, [model, face, condition, kind, x, y, z, pressure], outputs, **event_options)
        delete_comment.click(lambda mid, rid, ok: remove(mid, rid, ok, "comments"),
                             [model, comment, confirm_comment], outputs, **event_options)
        delete_condition.click(lambda mid, rid, ok: remove(mid, rid, ok, "boundaryConditions"),
                               [model, condition, confirm_condition], outputs, **event_options)
        incoming.upload(merge, [model, incoming], outputs, **event_options)
        export.click(user_errors(workspace.export_annotations), model, download, **event_options)
        solve.click(run_simulation, [model, mechanical_python, element_size, confirm_solve],
                    [simulation_status, simulation_results, contours, simulation_files, confirm_solve], **event_options)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--data-dir", default=os.environ.get("STEP_GRADIO_DATA", "gradio-data"))
    args = parser.parse_args()
    workspace = Workspace(args.data_dir)
    app = build_app(workspace)
    app.queue().launch(server_name="127.0.0.1", server_port=args.port, share=False,
                       allowed_paths=[str(STATIC), str(workspace.root / "previews"), str(workspace.root / "exports")])


if __name__ == "__main__":
    main()
