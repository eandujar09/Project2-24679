"""Official MCP startup remains isolated from simulation submission."""
import importlib.util
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import Mock,patch


class FluentMCPStartupTests(unittest.TestCase):
    def test_loading_startup_script_has_no_side_effects(self):
        path=Path(__file__).resolve().parents[2]/'scripts/fluent-mcp-server.py'
        spec=importlib.util.spec_from_file_location('studio_fluent_mcp_startup',path)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(module.main))

    def test_main_delegates_to_official_launcher_without_launching_solver(self):
        path=Path(__file__).resolve().parents[2]/'scripts/fluent-mcp-server.py'
        spec=importlib.util.spec_from_file_location('studio_fluent_mcp_startup',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        ansys=ModuleType('ansys');fluent=ModuleType('ansys.fluent')
        core=ModuleType('ansys.fluent.core');mcp=ModuleType('ansys.fluent.mcp')
        server=ModuleType('ansys.fluent.mcp.server');server.launcher=Mock()
        core.launch_fluent=Mock()
        ansys.fluent=fluent;fluent.core=core;fluent.mcp=mcp;mcp.server=server
        modules={'ansys':ansys,'ansys.fluent':fluent,'ansys.fluent.core':core,
                 'ansys.fluent.mcp':mcp,'ansys.fluent.mcp.server':server}
        with patch.dict('sys.modules',modules):module.main()
        server.launcher.assert_called_once_with()
        core.launch_fluent.assert_not_called()


if __name__=='__main__':unittest.main()
