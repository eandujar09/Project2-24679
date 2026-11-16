"""Example authored laminar-channel analysis, not a worker setup template.

Requires explicitly saved channel properties and every face condition. This file
is never automatically injected into a job; the submitted source owns every
meshing and physical choice below.
"""
tasks['Add Local Sizing'].AddChildToTask()
tasks['Add Local Sizing'].Execute()
tasks['Generate the Surface Mesh'].Arguments = {
    'CFDSurfaceMeshControls': {'MaxSize': ctx.analysis['mesh_size_mm']}}
tasks['Generate the Surface Mesh'].Execute()
description = tasks['Describe Geometry']
description.UpdateChildTasks(SetupTypeChanged=False)
description.Arguments = {'SetupType': 'The geometry consists of only fluid regions with no voids'}
description.UpdateChildTasks(SetupTypeChanged=True)
description.Execute()
tasks['Update Boundaries'].Execute()
ctx.update_regions()
tasks['Generate the Volume Mesh'].Arguments = {'VolumeFill': 'poly-hexcore'}
solver = ctx.generate_mesh(tolerance_mm=min(0.08, ctx.analysis['mesh_size_mm'] * 0.02))

setup = solver.settings.setup
setup.general.solver.type = 'pressure-based'
setup.general.solver.time = 'steady'
setup.models.energy.enabled = False
setup.models.viscous.model = 'laminar'
setup.general.operating_conditions.operating_pressure = ctx.analysis['operating_pressure']
setup.materials.fluid['channel-fluid'] = {}
material = setup.materials.fluid['channel-fluid']
material.density = {'option': 'value', 'value': ctx.analysis['density']}
material.viscosity = {'option': 'value', 'value': ctx.analysis['dynamic_viscosity']}
for name in setup.cell_zone_conditions.fluid.get_object_names():
    setup.cell_zone_conditions.fluid[name].general.material = 'channel-fluid'

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

solver.settings.solution.initialization.hybrid_initialize()
ctx.solve()
ctx.capture('pressure', 'pressure')
ctx.capture('velocity-magnitude', 'velocity')
