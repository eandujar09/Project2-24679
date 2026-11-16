"""Fluent uses Mechanical-style authored code, not worker physics templates."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,MagicMock

import test_fluent
from fluent.agent_run import ExecutionContext,run
from fluent.contract import validate_program,validate_request
from gradio_app.simulation import prepare_fluent_request


class FluentAgenticTests(unittest.TestCase):
    def setUp(self):
        fixture=test_fluent.FluentTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture
        self.root,self.workspace,self.mid=fixture.root,fixture.workspace,fixture.mid

    def test_saved_setup_and_ui_conditions_are_optional_like_mechanical(self):
        project=self.workspace.get(self.mid)
        project['fluentAnalysis']=None
        project['boundaryConditions']=[]
        with self.workspace.connect() as db:self.workspace._write(db,project)
        request=prepare_fluent_request(self.workspace,self.mid,dict(test_fluent.PROGRAM,code='print(ctx.geometry)'))
        self.assertIsNone(request['analysis'])
        self.assertEqual(validate_request(request),[])
        self.assertEqual(request['executionMode'],'agent-authored-v2')

    def test_old_fixed_template_is_removed_not_a_fallback(self):
        self.assertFalse(hasattr(ExecutionContext,'mesh'))
        self.assertFalse(hasattr(ExecutionContext,'configure'))
        for code in ('ctx.mesh()','ctx.configure()','meshing.switch_to_solver()'):
            with self.subTest(code=code),self.assertRaises(ValueError):
                validate_program(dict(test_fluent.PROGRAM,code=code))

    def test_prepare_only_imports_geometry_and_exposes_live_tasks(self):
        request=prepare_fluent_request(self.workspace,self.mid,test_fluent.PROGRAM)
        imported=Mock();session=Mock()
        session.workflow.TaskObject={'Import Geometry':imported}
        launcher=Mock(return_value=session)
        output=self.root/'prepare';output.mkdir()
        ctx=ExecutionContext(request,output,{},launcher=launcher)
        geometry=ctx.prepare()
        self.assertEqual(geometry['mappingStatus'],'not_meshed')
        self.assertEqual(len(geometry['faces']),6)
        self.assertGreater(geometry['cadVolumeMm3'],0)
        self.assertEqual(imported.Arguments['FileFormat'],'Mesh')
        self.assertEqual(imported.Arguments['MeshUnit'],'mm')
        imported.Execute.assert_called_once_with()
        session.switch_to_solver.assert_not_called()
        self.assertIsNone(ctx.solver)
        self.assertEqual(set(ctx.tasks),{'Import Geometry'})

    def test_generate_mesh_has_no_implicit_fill(self):
        ctx=ExecutionContext({'analysis':None,'boundaryConditions':[]},self.root,{})
        volume=Mock();volume.Arguments.get_state.return_value={}
        ctx.tasks={'Generate the Volume Mesh':volume}
        with self.assertRaisesRegex(ValueError,'explicit volume-mesh'):
            ctx.generate_mesh()
        volume.Execute.assert_not_called()

    def test_selection_never_guesses_face_zone_names(self):
        ctx=ExecutionContext({'analysis':None,'boundaryConditions':[]},self.root,{})
        ctx._mapping={'original-face':'verified-zone'}
        self.assertEqual(ctx.selection(['original-face']),['verified-zone'])
        for keys in ([],['missing']):
            with self.assertRaisesRegex(ValueError,'verified'):
                ctx.selection(keys)

    def test_authored_globals_are_handed_to_the_same_generated_code_runner(self):
        program=dict(test_fluent.PROGRAM,code="meshing.authored = True\nprint(ctx.geometry)\nprint(tasks['custom-task'])\nprint(workflow)")
        request=prepare_fluent_request(self.workspace,self.mid,program)
        ctx=Mock(solver=None,_iterated=False,geometry={'faces':[]},tasks={'custom-task':'live-task'})
        report=run(request,self.root/'authored',context_factory=lambda *args:ctx)
        self.assertEqual(report['status'],'succeeded')
        self.assertTrue(ctx.meshing.authored)
        self.assertIn('live-task',report['stdout'])
        self.assertEqual(report['verifiedSolves'],[])
        ctx.prepare.assert_called_once_with();ctx.close.assert_called_once_with()

    def test_active_non_laminar_equations_are_verified_without_hidden_initialization(self):
        ctx=self.fixture.solve_context()
        equations=ctx.solver.settings.solution.monitor.residual.equations
        names=['continuity','x-velocity','y-velocity','z-velocity','k','epsilon']
        values={name:Mock() for name in names}
        for value in values.values():value.is_active.return_value=True
        equations.get_object_names.return_value=names
        equations.__getitem__.side_effect=values.__getitem__
        ctx.solver.monitors.get_monitor_set_data.return_value=([1,2],{name:[0.01,1e-7] for name in names})
        self.assertEqual(ctx.solve()['status'],'Done')
        for value in values.values():self.assertEqual(value.absolute_criteria,1e-5)
        ctx.solver.settings.solution.initialization.hybrid_initialize.assert_not_called()

    def test_explicit_limits_are_required_without_a_saved_analysis(self):
        ctx=self.fixture.solve_context();ctx.analysis={}
        with self.assertRaisesRegex(ValueError,'iteration budget'):ctx.solve()
        ctx.solver.settings.solution.run_calculation.iterate.assert_not_called()
        self.assertEqual(ctx.solve(max_iterations=100,residual_tolerance=1e-5,
            mass_imbalance_tolerance=0.01)['status'],'Done')

    def test_total_iteration_budget_and_stale_repeat_history_are_rejected(self):
        ctx=self.fixture.solve_context();ctx._total_iterations=1950
        with self.assertRaisesRegex(ValueError,'2000'):ctx.solve()
        ctx.solver.settings.solution.run_calculation.iterate.assert_not_called()
        ctx=self.fixture.solve_context();ctx.solve()
        with self.assertRaisesRegex(ValueError,'stale'):ctx.solve()

    def test_saved_numerical_assumptions_cannot_be_silently_relaxed(self):
        ctx=self.fixture.solve_context()
        with self.assertRaisesRegex(ValueError,'saved residual_tolerance'):
            ctx.solve(residual_tolerance=0.1)
        ctx.solver.settings.solution.run_calculation.iterate.assert_not_called()

    def test_open_boundary_omission_fails_before_iteration(self):
        ctx=self.fixture.solve_context()
        ctx.solver.settings.setup.boundary_conditions.get_state.return_value = {
            'velocity_inlet':{'inlet':{}},'pressure_outlet':{'outlet':{},'other-outlet':{}}}
        with self.assertRaisesRegex(ValueError,'every actual open boundary'):ctx.solve()
        ctx.solver.settings.solution.run_calculation.iterate.assert_not_called()

    def test_constant_material_readback_accepts_canonical_value_not_expressions(self):
        ctx=ExecutionContext({'analysis':test_fluent.ANALYSIS,'boundaryConditions':[]},self.root,{})
        ctx.solver=MagicMock();setup=ctx.solver.settings.setup
        setup.general.solver.time.return_value='steady'
        setup.models.viscous.model.return_value='laminar'
        setup.models.energy.enabled.return_value=False
        setup.general.operating_conditions.operating_pressure.return_value=101325
        setup.cell_zone_conditions.fluid.get_object_names.return_value=['fluid']
        material=setup.materials.fluid.__getitem__.return_value
        material.density.option.return_value='value';material.density.value.return_value=1000
        material.viscosity.option.return_value='value';material.viscosity.value.return_value=0.001
        ctx._assert_setup()
        material.density.option.return_value='constant';ctx._assert_setup()
        material.density.option.return_value='expression'
        with self.assertRaisesRegex(ValueError,'differ'):ctx._assert_setup()
        material.density.option.return_value='value';material.viscosity.value.return_value=0.01
        with self.assertRaisesRegex(ValueError,'differ'):ctx._assert_setup()

    def test_example_is_complete_authored_code_not_runtime_injection(self):
        code=(Path(__file__).resolve().parents[2]/'examples/fluent-channel.py').read_text(encoding='utf-8')
        self.assertEqual(len(validate_program(dict(test_fluent.PROGRAM,code=code))),64)
        for fragment in ('VolumeFill','viscous.model','material.density','set_zone_type','hybrid_initialize','ctx.solve()'):
            self.assertIn(fragment,code)

    def test_native_face_preserving_example_keeps_checked_solve_and_scoping(self):
        code=(Path(__file__).resolve().parents[2]/'examples/fluent-native-steady-water.py').read_text()
        self.assertEqual(len(validate_program(dict(test_fluent.PROGRAM,code=code))),64)
        for fragment in ("'OneZonePer': 'face'","'CurvatureNormalAngle': 6.0",'ctx.selection',
                         'ctx.generate_mesh','high_order_term_relaxation','ctx.solve()'):
            self.assertIn(fragment,code)


if __name__=='__main__':unittest.main()
