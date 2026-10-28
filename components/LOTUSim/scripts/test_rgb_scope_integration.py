import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from rgb_observer_worker import detector_signature,run,effective_review_settings
from rgb_regions import empty_policy,region_signature

CONFIG={'schema':'lotusim-rgb-observer-config-1','model':'local-test','revision':'a'*40,
        'weightsSha256':'b'*64,'modelDirectory':'unused','device':'cpu','license':'test',
        'boxThreshold':.3,'textThreshold':.25,'nmsIou':.55,'tileSize':1024,
        'categories':[{'category':'buoy','displayName':'bouée','query':'a buoy'}]}

class ScopeIntegrationTests(unittest.TestCase):
    def test_signature_binds_exclusion_and_review(self):
        config=copy.deepcopy(CONFIG);baseline=detector_signature(config)
        config['searchRegionSignature']=region_signature(empty_policy())
        self.assertEqual(detector_signature(config),baseline)
        policy=empty_policy();policy['excludeRegions']=[{'id':'ship','polygon':[[0,.7],[.4,.7],[.5,1],[0,1]]}]
        config['searchRegionSignature']=region_signature(policy)
        self.assertNotEqual(detector_signature(config),baseline)
        config=copy.deepcopy(CONFIG);config['reviewSettings']={'crossClassIou':.9}
        self.assertNotEqual(detector_signature(config),baseline)
    def test_old_nms_setting_still_controls_same_class_dedup(self):
        config=copy.deepcopy(CONFIG);config['nmsIou']=.7
        self.assertEqual(effective_review_settings(config)['sameClassIou'],.7)
    def test_mask_directory_cannot_be_silently_unsigned(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with self.assertRaisesRegex(ValueError,'must agree'):
                run(root,root/'out',CONFIG,root,observer_masks=root)
    def test_declared_mask_source_requires_actual_mask_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);policy=empty_policy();policy['observerMaskSource']='unity_observer_visible_depth'
            path=root/'regions.json';path.write_text(json.dumps(policy))
            with self.assertRaisesRegex(ValueError,'must agree'):
                run(root,root/'out',CONFIG,root,regions=path)
    def test_worker_rejects_changed_policy_signature(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);config=copy.deepcopy(CONFIG);config['searchRegionSignature']='c'*64
            with self.assertRaisesRegex(ValueError,'signature differ'):
                run(root,root/'out',config,root)

if __name__=='__main__':unittest.main()
