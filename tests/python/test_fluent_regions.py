"""Worker-owned region selection must precede volume meshing."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from fluent.agent_run import select_fluid_region,update_fluid_regions


class FluentRegionTests(unittest.TestCase):
    def test_selects_volume_not_name_order_or_largest(self):
        regions=[{'name':'large','volumeMm3':500},{'name':'small','volumeMm3':100}]
        self.assertIs(select_fluid_region(regions,100),regions[1])

    def test_unique_fluid_and_obstacle(self):
        regions=[{'name':'fluid','volumeMm3':683133},{'name':'obstacle','volumeMm3':39309}]
        self.assertIs(select_fluid_region(regions,683200),regions[0])

    def test_missing_ambiguous_or_invalid_volume_fails_closed(self):
        for volumes,target in [([],100),([10,20],100),([100,100.1],100),
                               ([float('nan')],100),([float('inf')],100),([-1],100),([0],100),([100],0)]:
            with self.subTest(volumes=volumes,target=target),self.assertRaises(ValueError):
                select_fluid_region([{'name':str(i),'volumeMm3':v} for i,v in enumerate(volumes)],target)

    def session(self):
        utilities=Mock()
        utilities.get_objects.return_value=['mesh-object']
        utilities.get_regions.return_value=['obstacle','fluid']
        utilities.get_region_volume.side_effect=[[40],[100]]
        task=Mock()
        return SimpleNamespace(meshing_utilities=utilities),{'Update Regions':task},task

    def test_marks_obstacle_dead_and_supplies_old_values(self):
        session,tasks,task=self.session()
        evidence=update_fluid_regions(session,tasks,100)
        self.assertEqual(task.Arguments,{
            'RegionNameList':['obstacle','fluid'],'RegionTypeList':['dead','fluid'],
            'OldRegionNameList':['obstacle','fluid'],'OldRegionTypeList':['fluid','fluid']})
        task.Execute.assert_called_once_with()
        self.assertEqual([r['type'] for r in evidence['regions']],['dead','fluid'])

    def test_single_region_is_kept(self):
        session,tasks,task=self.session()
        session.meshing_utilities.get_regions.return_value=['fluid']
        session.meshing_utilities.get_region_volume.side_effect=[[100]]
        update_fluid_regions(session,tasks,100)
        self.assertEqual(task.Arguments['RegionTypeList'],['fluid'])

    def test_ambiguity_stops_before_updating_regions(self):
        session,tasks,task=self.session()
        session.meshing_utilities.get_region_volume.side_effect=[[100],[100]]
        with self.assertRaises(ValueError):update_fluid_regions(session,tasks,100)
        task.Execute.assert_not_called()

    def test_multiple_objects_or_bad_query_fails_closed(self):
        session,tasks,task=self.session()
        session.meshing_utilities.get_objects.return_value=['one','two']
        with self.assertRaises(ValueError):update_fluid_regions(session,tasks,100)
        task.Execute.assert_not_called()
        session,tasks,task=self.session()
        session.meshing_utilities.get_region_volume.side_effect=[[10,20],[100]]
        with self.assertRaises(ValueError):update_fluid_regions(session,tasks,100)
        task.Execute.assert_not_called()


if __name__=='__main__':unittest.main()
