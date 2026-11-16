"""Verify the worker-owned STL importer, without starting Fluent."""
from pathlib import Path
import unittest
from unittest.mock import Mock

from fluent.agent_run import import_surface_mesh


class FluentImportTests(unittest.TestCase):
    def test_stl_is_explicitly_imported_as_mesh_in_mm(self):
        task = Mock()
        workflow = Mock()
        workflow.TaskObject = {'Import Geometry':task}
        path = Path('job results')/'boundaries.stl'
        tasks = import_surface_mesh(workflow,path)
        workflow.InitializeWorkflow.assert_called_once_with(WorkflowType='Watertight Geometry')
        self.assertEqual(task.Arguments,{'FileFormat':'Mesh','MeshFileName':str(path),'MeshUnit':'mm','LengthUnit':'mm'})
        self.assertNotIn('FileName',task.Arguments)
        task.Execute.assert_called_once_with()
        self.assertIs(tasks,workflow.TaskObject)

    def test_format_is_set_before_import_execution(self):
        task = Mock()
        workflow = Mock()
        workflow.TaskObject = {'Import Geometry':task}
        def execute():
            self.assertEqual(task.Arguments['FileFormat'],'Mesh')
            self.assertEqual(task.Arguments['LengthUnit'],'mm')
            self.assertEqual(task.Arguments['MeshUnit'],'mm')
            self.assertEqual(task.Arguments['MeshFileName'],'boundaries.stl')
        task.Execute.side_effect = execute
        import_surface_mesh(workflow,'boundaries.stl')

    def test_import_failure_propagates_without_retrying_or_running_later_tasks(self):
        task = Mock()
        task.Execute.side_effect = ValueError('Actual importer failure')
        workflow = Mock()
        workflow.TaskObject = {'Import Geometry':task}
        with self.assertRaisesRegex(ValueError,'Actual importer failure'):
            import_surface_mesh(workflow,'boundaries.stl')
        task.Execute.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
