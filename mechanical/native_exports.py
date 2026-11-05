"""Create native Mechanical deliverables before the embedded application closes."""
from pathlib import Path


def save_native_exports(app, ns, output, report):
    output = Path(output)
    analyses = list(ns['Model'].Analyses)
    verified = (any(item.get('status') == 'Done' for item in report.get('verifiedSolves', []))
                or report.get('solutionStatus') == 'Done')
    if verified and analyses and all(str(a.Solution.Status) == 'Done' for a in analyses):
        settings = ns['Ansys'].ACT.Automation.Mechanical.ArchiveSettings(True, True)
        # Archive the saved .mechdb before exporting .mechdat changes its path.
        ns['ExtAPI'].DataModel.Project.Archive(str(output / 'simulation.mechpz'), True, settings)
        report['nativeArchive'] = {'file': 'simulation.mechpz', 'includesResults': True}
    if analyses:
        app.save_as(str(output / 'setup.mechdat'), overwrite=True)
