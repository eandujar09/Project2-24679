"""Deterministic Mechanical 261 worker; run in a PyMechanical environment.

python -m mechanical.run --request request.json --output-dir new-results-folder
"""

import argparse
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import shutil
import sys
import traceback

from .contract import match_faces, validate_request, write_json


def run(request_path, output, mapping_only=False):
    request_path, output = Path(request_path).resolve(), Path(output).resolve()
    # Never replace a previous run, project, or solver result.
    output.mkdir(parents=True, exist_ok=False)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    report = {"status": "failed", "modelId": request.get("modelId"), "analysis": "linear static structural",
              "settings": request.get("settings"), "requestSHA256": hashlib.sha256(request_path.read_bytes()).hexdigest()}
    app = None
    try:
        applied = validate_request(request)
        shutil.copy2(request_path, output / "request.json")
        shutil.copy2(request["stepFile"], output / "source.step")
        print("Starting Mechanical 261", flush=True)
        from ansys.mechanical.core import App
        app = App(version=261, private_appdata=True)
        app.update_globals(globals())
        report["mechanicalVersion"] = str(ExtAPI.Application.WBVersion)
        report["pyMechanicalVersion"] = importlib.metadata.version("ansys-mechanical-core")
        if report["mechanicalVersion"] != "261":
            raise ValueError("Mechanical version does not match the job's pinned version.")
        ExtAPI.Application.ActiveUnitSystem = MechanicalUnitSystem.StandardNMM
        preferences = Ansys.ACT.Mechanical.Utilities.GeometryImportPreferences()
        preferences.FacetQuality = GeometryImportPreference.FacetQuality.VeryFine
        importer = Model.GeometryImportGroup.AddGeometryImport()
        importer.Import(str(output / "source.step"), GeometryImportPreference.Format.Automatic, preferences)
        bodies = list(Model.Geometry.GetChildren(DataModelObjectCategory.Body, True))
        if len(bodies) != 1 or str(bodies[0].GetGeoBody().BodyType) != "GeoBodySolid":
            raise ValueError("Only a single solid is supported; contact/shell/beam assumptions must be specified separately.")
        body = bodies[0]
        body.Material = request["settings"]["material"]
        if body.Material != request["settings"]["material"]:
            raise ValueError("Mechanical did not assign the requested material.")
        if str(ExtAPI.DataModel.GeoData.Unit) != "mm":
            raise ValueError("Mechanical CAD geometry is not in millimeters.")
        faces = {int(f.Id): f for f in body.GetGeoBody().Faces}
        # Some translators expose periodic seam edges; others omit them. In a
        # closed single solid, a real inter-face trim edge has two incident
        # faces, whereas a surface's artificial seam belongs only to itself.
        face_edges = {key: [edge for edge in face.Edges if len({int(owner.Id) for owner in edge.Faces}) > 1]
                      for key, face in faces.items()}
        edges = {int(edge.Id): edge for boundary in face_edges.values() for edge in boundary}
        candidates = [{"id": key, "areaMm2": float(face.Area), "centroidMm": list(face.Centroid),
                       "verticesMm": [[float(v.X), float(v.Y), float(v.Z)] for v in face.Vertices],
                       "edgeIds": [int(edge.Id) for edge in face_edges[key]],
                       "boundarySamplesMm": [list(edge.PointAtParam(float(edge.Extents[0]) +
                                              (float(edge.Extents[1]) - float(edge.Extents[0])) * i / 64.0))
                                             for edge in face_edges[key] for i in range(65)]}
                      for key, face in faces.items()]

        def evaluate(face_id, point):
            face = faces[face_id]
            uv = face.ParamAtPoint(point)
            return list(face.PointAtParam(uv[0], uv[1])), list(face.NormalAtParam(uv[0], uv[1]))

        def evaluate_edge(edge_id, point):
            edge = edges[edge_id]
            low, high = sorted(float(t) for t in edge.Extents)
            parameter = float(edge.ParamAtPoint(point))
            if distance_between_endpoints(edge) < 1e-7 and high > low:
                parameter = low + (parameter - low) % (high - low)
            parameter = max(low, min(high, parameter))
            return list(edge.PointAtParam(parameter))

        def distance_between_endpoints(edge):
            a, b = edge.StartVertex, edge.EndVertex
            return math.sqrt((a.X - b.X) ** 2 + (a.Y - b.Y) ** 2 + (a.Z - b.Z) ** 2)

        mapping, evidence = match_faces(request["faceSignatures"], candidates, evaluate, evaluate_edge=evaluate_edge)
        report["faceMapping"] = evidence
        report["appliedConditions"] = applied
        write_json(output / "face-mapping.json", evidence)
        print("Mapped all {} CAD faces unambiguously".format(len(mapping)), flush=True)
        if mapping_only:
            report["status"] = "validated"
            report["note"] = "Geometry and face mapping validated only; no mesh or solve was performed."
            return report
        analysis = Model.AddStaticStructuralAnalysis()
        analysis.Name = "Annotated linear static structural"
        settings = analysis.IAnalysisSettings
        settings.NumberOfSteps = 1
        settings.LargeDeflection = False
        settings.WeakSprings = WeakSpringsType.Off
        settings.SolverType = SolverType.Direct
        settings.AutomaticTimeStepping = AutomaticTimeStepping.Off
        settings.NumberOfSubSteps = 1
        settings.StepEndTime = Quantity(1, "s")
        config = ExtAPI.Application.SolveConfigurations["My Computer"]
        config.SolveProcessSettings.MaxNumberOfCores = 1
        config.SolveProcessSettings.DistributeSolution = False
        config.SolveProcessSettings.NumberOfGPUDevices = 0

        def selection(ids):
            info = ExtAPI.SelectionManager.CreateSelectionInfo(SelectionTypeEnum.GeometryEntities)
            info.Ids = ids
            return info

        for number, condition in enumerate(applied, 1):
            kind, values = condition["type"], condition["values"]
            location = selection([mapping[condition["faceKey"]]])
            if kind == "fixed":
                load = analysis.AddFixedSupport()
            elif kind in ("force", "displacement"):
                load = analysis.AddForce() if kind == "force" else analysis.AddDisplacement()
                load.DefineBy = LoadDefineBy.Components
                for axis in "xyz":
                    component = getattr(load, axis.upper() + "Component")
                    component.Output.DiscreteValues = [Quantity(values[axis], "N" if kind == "force" else "mm")]
            else:
                load = analysis.AddPressure()
                load.Magnitude.Output.DiscreteValues = [Quantity(values["magnitude"], "MPa")]
            load.Name = "{:03d} {} {}".format(number, kind, condition["faceKey"])
            load.Location = location
        mesh = Model.Mesh
        mesh.ElementSize = Quantity(request["settings"]["elementSizeMm"], "mm")
        mesh.ElementOrder = ElementOrder.Quadratic
        method = mesh.AddAutomaticMethod()
        method.Location = selection([body.GetGeoBody().Id])
        method.Method = MethodType.AllTriAllTet
        method.Algorithm = MeshMethodAlgorithm.PatchConforming
        app.save(str(output / "model.mechdb"))
        print("Generating quadratic tetrahedral mesh", flush=True)
        mesh.GenerateMesh()
        mesh_data = ExtAPI.DataModel.MeshDataByName("Global")
        report["mesh"] = {"nodes": int(mesh_data.NodeCount), "elements": int(mesh_data.ElementCount),
                          "elementOrder": "quadratic", "method": "patch-conforming tetrahedra"}
        if not report["mesh"]["nodes"] or not report["mesh"]["elements"]:
            raise ValueError("Mechanical did not generate a mesh.")
        if max(report["mesh"]["nodes"], report["mesh"]["elements"]) > 32000:
            raise ValueError("Mesh exceeds this runner's conservative 32,000-node/element limit. Increase element size.")
        deformation = analysis.Solution.AddTotalDeformation()
        deformation.Name = "Total deformation (mm)"
        stress = analysis.Solution.AddEquivalentStress()
        stress.Name = "Equivalent von Mises stress (MPa)"
        print("Solving on one CPU core (weak springs off)", flush=True)
        analysis.Solution.Solve(True, config)
        report["solutionStatus"] = str(analysis.Solution.Status)
        report["messages"] = [{"severity": str(message.Severity), "text": str(message.DisplayString)}
                              for message in ExtAPI.Application.Messages]
        if report["solutionStatus"] != "Done":
            raise ValueError("Mechanical solve did not finish successfully: " + report["solutionStatus"])
        analysis.Solution.EvaluateAllResults()
        report["results"] = {}
        for key, result, unit in (("totalDeformation", deformation, "mm"), ("vonMisesStress", stress, "MPa")):
            maximum, minimum = result.Maximum, result.Minimum
            if str(maximum.Unit) != unit or str(minimum.Unit) != unit:
                raise ValueError("Unexpected result units: " + str(maximum.Unit))
            report["results"][key] = {"minimum": float(minimum.Value), "maximum": float(maximum.Value), "unit": unit}
            if not all(math.isfinite(value) for value in (float(minimum.Value), float(maximum.Value))):
                raise ValueError("Result contains non-finite extrema: " + key)
            result.ExportToTextFile(str(output / (key + ".txt")))
            result.Activate()
            ExtAPI.Graphics.Camera.SetSpecificViewOrientation(ViewOrientationType.Iso)
            ExtAPI.Graphics.Camera.SetFit()
            ExtAPI.Graphics.ExportImage(str(output / (key + ".png")))
        app.save(str(output / "model.mechdb"))
        report["status"] = "succeeded"
        report["limitations"] = ["Linear elastic, small deformation, one solid, one load step.",
                                  "Material is Mechanical 261's Structural Steel library definition.",
                                  "No mesh-convergence, yield/failure, contact, fatigue, or buckling assessment.",
                                  "Repeatable setup is not a guarantee of bit-identical solver output or engineering validity."]
        print("Solve and result exports succeeded", flush=True)
    except Exception as exc:
        report["error"] = str(exc)
        if hasattr(exc, "diagnostics"):
            report["mappingDiagnostics"] = exc.diagnostics
            write_json(output / "mapping-diagnostics.json", exc.diagnostics)
        traceback.print_exc()
    finally:
        write_json(output / "report.json", report)
        if app is not None:
            app.close()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--output-dir", required=True, help="Must not already exist")
    parser.add_argument("--map-only", action="store_true", help="Validate exact face mapping without meshing or solving")
    args = parser.parse_args()
    report = run(args.request, args.output_dir, mapping_only=args.map_only)
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["status"] in ("succeeded", "validated") else 1


if __name__ == "__main__":
    sys.exit(main())
