import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from rgb_regions import (empty_policy,validate_regions,exclusion_mask,masked_rgb,
                         profile_matches,region_signature,prepare_search_inputs)

class RegionTests(unittest.TestCase):
    def policy(self):
        p=empty_policy();p['excludeRegions']=[{'id':'ownship','polygon':[[0,.7],[.4,.7],[.5,1],[0,1]]}];return p
    def test_no_polygon_masks_no_pixels(self):
        self.assertEqual(exclusion_mask((80,60),empty_policy()).getbbox(),None)
    def test_polygon_changes_only_selected_pixels_and_not_source(self):
        image=Image.new('RGB',(80,60),(3,4,5));mask=exclusion_mask(image.size,self.policy())
        result=masked_rgb(image,mask)
        self.assertEqual(result.getpixel((2,58)),(127,127,127))
        self.assertEqual(result.getpixel((70,58)),(3,4,5))
        self.assertEqual(image.getpixel((2,58)),(3,4,5))
    def test_finite_normalized_polygon_required(self):
        for value in (float('nan'),-1,2,True):
            policy=self.policy();policy['excludeRegions'][0]['polygon'][0][0]=value
            with self.assertRaises(ValueError):validate_regions(policy)
    def test_intersecting_polygon_rejected(self):
        policy=self.policy();policy['excludeRegions'][0]['polygon']=[[0,0],[1,1],[0,1],[1,0],[.4,.1]]
        with self.assertRaises(ValueError):validate_regions(policy)
    def test_signature_changes_with_geometry_not_notes(self):
        policy=self.policy();original=region_signature(policy);policy['notes']='metadata'
        self.assertEqual(original,region_signature(policy))
        policy['excludeRegions'][0]['polygon'][0][1]=.6
        self.assertNotEqual(original,region_signature(policy))
    def test_profile_requires_all_camera_fields_and_tolerance(self):
        source={'width':3840,'height':2160,'verticalFovDeg':55,'observerDeckCamera':True,
                'viewHeadingDeg':15,'routeHeadingDeg':0,'observerDeckOffsetM':{'x':30.2999992}}
        match={'aspectRatio':16/9,'verticalFovDeg':55,'observerDeckCamera':True,
               'relativeViewHeadingDeg':15,'observerDeckOffsetM.x':30.3}
        self.assertTrue(profile_matches(source,match))
        source['verticalFovDeg']=60;self.assertFalse(profile_matches(source,match))
        self.assertFalse(profile_matches(source,{}))
    def test_mismatched_mask_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'mask.png';Image.new('L',(10,10),255).save(path)
            with self.assertRaisesRegex(ValueError,'dimensions'):exclusion_mask((20,20),empty_policy(),path)
            Image.new('L',(20,20),100).save(path)
            with self.assertRaisesRegex(ValueError,'binary'):exclusion_mask((20,20),empty_policy(),path)
    def test_explicit_directory_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);output=root/'out';output.mkdir()
            with self.assertRaisesRegex(ValueError,'JSON file'):prepare_search_inputs(root,output,[],root,root)
    def test_claimed_unity_masks_require_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);output=root/'out';output.mkdir()
            policy=empty_policy();policy['observerMaskSource']='unity_observer_visible_depth'
            (root/'rgb-observer-regions.json').write_text(json.dumps(policy))
            with self.assertRaisesRegex(ValueError,'manifest'):prepare_search_inputs(root,output,[],root)
    def test_verified_pair_only_and_no_annotations_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);campaign=root/'campaign';(campaign/'rgb').mkdir(parents=True)
            (campaign/'observer-exclusion').mkdir();output=root/'out';output.mkdir()
            rgb=campaign/'rgb/f000000.png';mask=campaign/'observer-exclusion/f000000.png'
            Image.new('RGB',(20,12),(10,20,30)).save(rgb);Image.new('L',(20,12),0).save(mask)
            sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
            manifest={'schema':'lotusim-observer-exclusion-1','coordinateSystem':'image_pixels_top_left',
                      'maskDirectory':'observer-exclusion','foregroundValue':255,'source':'unity_observer_visible_depth',
                      'observerOnly':True,'width':20,'height':12,'frames':[{
                          'imageFile':'rgb/f000000.png','maskFile':'observer-exclusion/f000000.png',
                          'rgbSha256':sha(rgb),'maskSha256':sha(mask),'unityFrame':7}]}
            (campaign/'observer-exclusion.json').write_text(json.dumps(manifest))
            # Annotations intentionally invalid: these must never be consulted.
            (campaign/'annotations').mkdir();(campaign/'annotations/f000000.json').write_text('NOT JSON')
            with Image.open(rgb) as image:pixel_hash=hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()
            mapping=[{'workerImage':'i000000.png','sourceImage':'f000000.png','width':20,'height':12,'rgbPixelSha256':pixel_hash}]
            prepared=prepare_search_inputs(campaign,output,mapping,root)
            self.assertEqual(prepared['policy']['observerMaskSource'],'unity_observer_visible_depth')
            self.assertTrue((prepared['masksDirectory']/'i000000.png').is_file())
            self.assertFalse((output/'input/annotations').exists())
            Image.new('L',(20,12),255).save(mask)
            second=root/'out2';second.mkdir()
            with self.assertRaisesRegex(ValueError,'hash mismatch'):prepare_search_inputs(campaign,second,mapping,root)

    def pair_fixture(self,root):
        campaign=root/'campaign';(campaign/'rgb').mkdir(parents=True)
        (campaign/'observer-exclusion').mkdir();output=root/'out';output.mkdir()
        rgb=campaign/'rgb/f000000.png';mask=campaign/'observer-exclusion/f000000.png'
        Image.new('RGB',(20,12),(10,20,30)).save(rgb);Image.new('L',(20,12),0).save(mask)
        sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
        with Image.open(rgb) as image:pixel_hash=hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()
        manifest={'schema':'lotusim-observer-exclusion-1','coordinateSystem':'image_pixels_top_left',
                  'maskDirectory':'observer-exclusion','foregroundValue':255,'source':'unity_observer_visible_depth',
                  'observerOnly':True,'width':20,'height':12,'frames':[{
                      'imageFile':'rgb/f000000.png','maskFile':'observer-exclusion/f000000.png',
                      'rgbSha256':sha(rgb),'maskSha256':sha(mask),'unityFrame':7}]}
        mapping=[{'workerImage':'i000000.png','sourceImage':'f000000.png','width':20,'height':12,'rgbPixelSha256':pixel_hash}]
        (campaign/'observer-exclusion.json').write_text(json.dumps(manifest))
        return campaign,output,rgb,mask,manifest,mapping

    def test_changed_source_and_updated_manifest_cannot_pair_with_old_staged_rgb(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            campaign,output,rgb,mask,manifest,mapping=self.pair_fixture(root)
            Image.new('RGB',(20,12),(60,70,80)).save(rgb)
            Image.new('L',(20,12),255).save(mask)
            manifest['frames'][0]['rgbSha256']=hashlib.sha256(rgb.read_bytes()).hexdigest()
            manifest['frames'][0]['maskSha256']=hashlib.sha256(mask.read_bytes()).hexdigest()
            (campaign/'observer-exclusion.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'source RGB differs from staged'):
                prepare_search_inputs(campaign,output,mapping,root)

    def test_pairing_requires_mapping_pixel_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            campaign,output,rgb,mask,manifest,mapping=self.pair_fixture(root)
            del mapping[0]['rgbPixelSha256']
            with self.assertRaisesRegex(ValueError,'pixel hash is required'):
                prepare_search_inputs(campaign,output,mapping,root)

    def test_changed_staged_rgb_is_rejected_even_when_source_pair_is_valid(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            campaign,output,rgb,mask,manifest,mapping=self.pair_fixture(root)
            (output/'input/rgb').mkdir(parents=True)
            Image.new('RGB',(20,12),(100,110,120)).save(output/'input/rgb/i000000.png')
            with self.assertRaisesRegex(ValueError,'staged RGB pixel hash mismatch'):
                prepare_search_inputs(campaign,output,mapping,root)

    def test_verified_mask_is_copied_from_hashed_buffer(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            campaign,output,rgb,mask,manifest,mapping=self.pair_fixture(root)
            before=mask.read_bytes()
            result=prepare_search_inputs(campaign,output,mapping,root)
            self.assertEqual((result['masksDirectory']/'i000000.png').read_bytes(),before)
            self.assertEqual(result['provenance']['frames'][0]['rgbPixelSha256'],mapping[0]['rgbPixelSha256'])

    def test_pairing_checks_native_rgb_dimensions_independently_of_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            campaign,output,rgb,mask,manifest,mapping=self.pair_fixture(root)
            mapping[0]['width']=21
            with self.assertRaisesRegex(ValueError,'source RGB/native dimensions'):
                prepare_search_inputs(campaign,output,mapping,root)

if __name__=='__main__':unittest.main()
