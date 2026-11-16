"""Authored reproduction of the converged saved-water run, not a worker default.

Requires approved ctx.analysis and ctx.conditions. The archive of the verified
run retains the exact executed source; this readable example uses the same calls.
"""
workflow.InitializeWorkflow(WorkflowType='Watertight Geometry')
tasks = workflow.TaskObject
ctx.tasks = tasks
cad_options = {'OneZonePer': 'face', 'OneObjectPer': 'Body', 'ImportCurvatureDataFromCAD': True}
tasks['Import Geometry'].Arguments = {
    'FileFormat': 'CAD File', 'FileName': ctx.artifact('source.step'),
    'LengthUnit': 'mm', 'CadImportOptions': cad_options}
tasks['Import Geometry'].Execute()
ctx.geometry['importMethod'] = 'native-step-original-face-zones'
tasks['Add Local Sizing'].AddChildToTask()
tasks['Add Local Sizing'].Execute()
tasks['Generate the Surface Mesh'].Arguments = {
    'CadImportOptions': cad_options,
    'CFDSurfaceMeshControls': {'MaxSize': ctx.analysis['mesh_size_mm'], 'CurvatureNormalAngle': 6.0}}
tasks['Generate the Surface Mesh'].Execute()
description = tasks['Describe Geometry']
description.UpdateChildTasks(SetupTypeChanged=False)
description.Arguments = {'SetupType': 'The geometry consists of only fluid regions with no voids'}
description.UpdateChildTasks(SetupTypeChanged=True)
description.Execute()
tasks['Update Boundaries'].Execute()
ctx.update_regions()
tasks['Generate the Volume Mesh'].Arguments = {
    'VolumeFill': 'polyhedra',
    'VolumeFillControls': {'TetPolyMaxCellLength': ctx.analysis['mesh_size_mm'], 'GrowthRate': 1.4},
    'VolumeMeshPreferences': {'PolyFeatureAngle': 5.0}}
solver = ctx.generate_mesh(tolerance_mm=min(0.08, ctx.analysis['mesh_size_mm'] * 0.02))

setup = solver.settings.setup
setup.general.solver.type = 'pressure-based'
setup.general.solver.time = 'steady'
setup.models.energy.enabled = False
setup.models.viscous.model = 'laminar'
setup.general.operating_conditions.operating_pressure = ctx.analysis['operating_pressure']
setup.materials.fluid['saved-water'] = {}
material = setup.materials.fluid['saved-water']
material.density = {'option': 'value', 'value': ctx.analysis['density']}
material.viscosity = {'option': 'value', 'value': ctx.analysis['dynamic_viscosity']}
for name in setup.cell_zone_conditions.fluid.get_object_names():
    setup.cell_zone_conditions.fluid[name].general.material = 'saved-water'
boundaries = setup.boundary_conditions
for row in ctx.conditions:
    name = ctx.selection([row['faceKey']])[0]
    kind, values = row['type'], row['values']
    boundaries.set_zone_type(zone_list=[name], new_type=kind.replace('_', '-'))
    zone = getattr(boundaries, kind)[name]
    if kind == 'velocity_inlet':
        zone.momentum.velocity_specification_method = 'Components'
        zone.momentum.reference_frame = 'Absolute'
        for i, axis in enumerate('xyz'):
            zone.momentum.velocity_components[i].value = values[axis]
    elif kind == 'pressure_outlet':
        zone.momentum.gauge_pressure.value = values['gauge_pressure']
    elif kind == 'wall':
        zone.momentum.wall_motion = 'Stationary Wall'
        zone.momentum.shear_condition = 'No Slip'

solver.settings.solution.controls.p_v_controls.explicit_pressure_under_relaxation = 0.2
solver.settings.solution.controls.p_v_controls.explicit_momentum_under_relaxation = 0.5
solver.settings.solution.methods.high_order_term_relaxation.enable = True
solver.settings.solution.methods.high_order_term_relaxation.relaxation_factor = 0.25
solver.settings.solution.run_calculation.pseudo_time_settings.time_step_method.time_step_size_scale_factor = 0.1
solver.settings.solution.initialization.hybrid_initialize()
ctx.solve()
ctx.capture('pressure', 'pressure')
ctx.capture('velocity-magnitude', 'velocity')
