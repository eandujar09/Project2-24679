"""Real OpenCascade enclosure/subtraction tests; never consumes a solver license."""
import copy
import hashlib
import json
import math
import unittest
import uuid
from unittest.mock import patch

import test_mechanical
from gradio_app.chat_state import ChatWorkspace
from gradio_app.chat_tools import apply_tool
from gradio_app.chat_confirmations import propose,consume_confirmation
from gradio_app.domain_geometry import build_domain,volume,solids
from gradio_app.fluid_domain import validate_domain
from gradio_app.geometry import read_shape


BOX = dict(min_x=-5,min_y=-10,min_z=-5,max_x=15,max_y=30,max_z=35)
CYLINDER = dict(origin_x=5,origin_y=10,origin_z=-5,axis_x=0,axis_y=0,axis_z=1,radius=20,length=40)


class DomainGeometryTests(unittest.TestCase):
    def setUp(self):
        fixture = test_mechanical.RequestTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.workspace,self.mid,self.root = fixture.workspace,fixture.mid,fixture.root
        self.source = self.workspace.root/'models'/f'{self.mid}.step'
        self.sid = uuid.uuid4().hex
        self.service = ChatWorkspace(self.workspace)
        self.service.open_model(self.sid,self.workspace.get(self.mid))

    def args(self,**values):
        return dict(model_id=self.service.session(self.sid).model_id,revision=self.service.session(self.sid).revision,**values)

    def definition(self,kind='box',role='obstacle',params=None):
        return validate_domain(kind,role,params or (BOX if kind == 'box' else CYLINDER),'Explicit test domain.')

    def test_real_box_subtraction_is_watertight_one_region_and_preserves_source(self):
        before = self.source.read_bytes()
        report = build_domain(self.source,self.definition(),self.root/'fluid.step')
        self.assertEqual(report['connectedRegions'],1)
        self.assertTrue(report['watertight'])
        self.assertAlmostEqual(report['fluidVolumeMm3'],20*40*40-10*20*30,places=5)
        self.assertAlmostEqual(report['minimumClearanceMm'],5,places=5)
        self.assertEqual(set(report['faceRoles'].values()),{'min_x','max_x','min_y','max_y','min_z','max_z','obstacle_wall'})
        self.assertEqual(self.source.read_bytes(),before)

    def test_cylindrical_obstacle_subtraction_and_empty_reference_domain(self):
        for role in ('obstacle','reference'):
            path = self.root/f'{role}.step'
            report = build_domain(self.source,self.definition('cylinder',role),path)
            expected = math.pi*20**2*40-(6000 if role == 'obstacle' else 0)
            self.assertAlmostEqual(report['fluidVolumeMm3'],expected,places=4)
            self.assertEqual(len(solids(read_shape(path))),1)

    def test_contact_outside_obstacle_and_custom_are_rejected_without_overwrite(self):
        for params in [dict(BOX,min_x=0),dict(BOX,max_x=5)]:
            with self.assertRaises(ValueError):
                build_domain(self.source,self.definition(params=params),self.root/'invalid.step')
        with self.assertRaisesRegex(ValueError,'Construction supports'):
            build_domain(self.source,self.definition('custom','reference',{'radius':10}),self.root/'custom.step')
        with self.assertRaisesRegex(ValueError,'new file'):
            build_domain(self.source,self.definition(),self.source)

    def test_enclosed_obstacle_cavity_produces_disconnected_fluid_and_fails(self):
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
        from OCP.gp import gp_Pnt
        from test_workspace import write_step
        obstacle = BRepAlgoAPI_Cut(BRepPrimAPI_MakeBox(10,20,30).Shape(),
                                  BRepPrimAPI_MakeBox(gp_Pnt(2,2,2),6,16,26).Shape()).Shape()
        path = self.root/'sealed-cavity.step'; write_step(path,obstacle)
        with self.assertRaisesRegex(ValueError,'disconnected'):
            build_domain(path,self.definition(),self.root/'disconnected.step')

    def test_clearance_suggestion_keeps_fixed_y_and_does_not_change_setup(self):
        params = dict(BOX,min_x=0,max_x=10,min_z=0,max_z=30)
        self.workspace.set_fluid_domain(self.mid,'box','obstacle',params,'Touching test box.')
        before = self.workspace.get(self.mid)
        suggested = apply_tool(self.service,self.sid,'suggest_fluid_domain',self.args(fixed_axes=['y']))
        self.assertEqual(suggested['parameters']['min_y'],BOX['min_y'])
        self.assertEqual(suggested['parameters']['max_y'],BOX['max_y'])
        self.assertLess(suggested['parameters']['min_x'],0)
        self.assertGreater(suggested['parameters']['max_z'],30)
        self.assertEqual(self.workspace.get(self.mid),before)

    def test_guided_build_changes_active_model_only_after_confirmation_and_deduplicates(self):
        self.workspace.set_fluid_domain(self.mid,'box','obstacle',BOX,'External box.')
        before = self.workspace.get(self.mid)
        propose(self.service,self.sid,'create_fluid_domain',self.args(),'Create the fluid volume.')
        self.assertEqual(self.service.session(self.sid).model_id,self.mid)
        approved = consume_confirmation(self.service,self.sid,'Confirm')
        result = apply_tool(self.service,self.sid,approved['tool'],approved['arguments'])
        derived = self.workspace.get(self.service.session(self.sid).model_id)
        self.assertTrue(result['created'])
        self.assertNotEqual(derived['id'],self.mid)
        self.assertEqual(self.workspace.get(self.mid),before)
        self.assertEqual(derived['boundaryConditions'],[])
        self.assertEqual(derived['fluidDomain']['status'],'ready')
        self.assertEqual(derived['domainGeneration']['sourceModelId'],self.mid)
        self.assertIn('boundaryRole',derived['faces'][0])
        self.assertIn('Fluid geometry created',self.service.session(self.sid).messages[-1]['content'])
        self.assertTrue(json.loads(self.service.viewer(self.sid))['fluidDomainView'])
        original_count = len(self.workspace.projects())
        duplicate = self.workspace.create_fluid_domain(self.mid,before['fluidDomain'])
        self.assertEqual(duplicate['id'],derived['id'])
        self.assertEqual(len(self.workspace.projects()),original_count)
        self.assertFalse(self.service.session(self.sid).running)

    def test_failed_build_and_timeout_retain_active_cad_and_annotations(self):
        self.workspace.set_fluid_domain(self.mid,'box','obstacle',dict(BOX,min_x=0),'Touching obstacle.')
        before = self.workspace.get(self.mid)
        with self.assertRaisesRegex(ValueError,'touches'):
            apply_tool(self.service,self.sid,'create_fluid_domain',self.args())
        self.assertEqual(self.service.session(self.sid).model_id,self.mid)
        self.assertEqual(self.workspace.get(self.mid),before)
        self.assertFalse(self.service.session(self.sid).domain_building)
        import subprocess
        with patch('gradio_app.backend.subprocess.run',side_effect=subprocess.TimeoutExpired('cad',1)):
            with self.assertRaisesRegex(ValueError,'time limit'):
                self.workspace.create_fluid_domain(self.mid,before['fluidDomain'],timeout_seconds=1)

    def test_rotated_cylinder_and_corrupt_cached_geometry_are_checked(self):
        p = dict(origin_x=-5,origin_y=10,origin_z=15,axis_x=2,axis_y=0,axis_z=0,radius=25,length=20)
        report = build_domain(self.source,self.definition('cylinder','obstacle',p),self.root/'rotated.step')
        self.assertEqual(report['connectedRegions'],1)
        self.assertGreater(report['minimumClearanceMm'],0)
        self.workspace.set_fluid_domain(self.mid,'box','obstacle',BOX,'Cache test.')
        domain = self.workspace.get(self.mid)['fluidDomain']
        derived = self.workspace.create_fluid_domain(self.mid,domain)
        cached = self.workspace.root/'models'/f'{derived["id"]}.step'
        cached.write_bytes(b'User-modified file; do not overwrite.')
        with self.assertRaisesRegex(ValueError,'missing or changed'):
            self.workspace.create_fluid_domain(self.mid,domain)
        self.assertEqual(cached.read_bytes(),b'User-modified file; do not overwrite.')


if __name__ == '__main__':
    unittest.main()
