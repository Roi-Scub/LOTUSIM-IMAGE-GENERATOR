#!/usr/bin/env python3
"""RGB observer boundary/coordinate tests; no model or Gazebo process needed."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
from rgb_observer import stage, compare
from rgb_observer_worker import iou, suppress, category_for, validate_config


class ObserverTests(unittest.TestCase):
    def test_iou_and_nms(self):
        self.assertEqual(iou([0,0,10,10],[0,0,10,10]),1)
        self.assertEqual(iou([0,0,10,10],[10,0,10,10]),0)
        self.assertEqual(len(suppress([{"bbox":[0,0,10,10],"score":.8},{"bbox":[1,1,10,10],"score":.7}],.5)),1)

    def test_configuration_does_not_accept_scene_fields(self):
        c=json.loads((Path(__file__).resolve().parents[1]/"assets/perception/rgb_observer.json").read_text())
        validate_config(c)
        c["poses"]=[1,2,3]
        with self.assertRaises(ValueError):validate_config(c)

    def test_ambiguous_model_labels_are_not_forced_to_known_class(self):
        classes=[{"query":"a boat","category":"boat"},{"query":"a buoy","category":"buoy"}]
        self.assertEqual(category_for("a boat a buoy",classes)["category"],"unknown")
        self.assertEqual(category_for("a boat",classes)["category"],"boat")

    def test_stage_strips_names_and_does_not_copy_truth(self):
        from PIL import Image
        with tempfile.TemporaryDirectory(prefix="rgb-observer-test-") as folder:
            root=Path(folder);rgb=root/"rgb";rgb.mkdir();image=Image.new("RGB",(20,12),(40,50,60));image.save(rgb/"Buoy_SECRET.png")
            (root/"annotations").mkdir();(root/"annotations/secret.json").write_text("NEVER PASS TO WORKER")
            output=root/"output";output.mkdir();mapping=stage(rgb,output)
            self.assertEqual([p.name for p in (output/"input/rgb").iterdir()],["i000000.png"])
            self.assertEqual(Image.open(output/"input/rgb/i000000.png").tobytes(),image.tobytes())
            self.assertEqual(mapping[0]["sourceImage"],"Buoy_SECRET.png")
            self.assertFalse((output/"input/annotations").exists())
            with self.assertRaises(ValueError):stage(root/"annotations",root/"bad")

    def test_comparison_class_aware_and_no_fake_matches(self):
        with tempfile.TemporaryDirectory(prefix="rgb-compare-test-") as folder:
            root=Path(folder);pred=root/"pred";truth=root/"truth";pred.mkdir();truth.mkdir()
            mapping=[{"workerImage":"i000000.png","sourceImage":"f000000.png","rgbPixelSha256":"abc","width":100,"height":80}]
            prediction={"rgbPixelSha256":"abc","predictions":[{"category":"sailboat","score":.9,"bbox":[10,10,20,20]},{"category":"buoy","score":.8,"bbox":[50,20,10,10]}]}
            reference={"width":100,"height":80,"annotations":[{"category":"sailboat","bbox":[10,10,20,20],"recognitionStatus":"R"},{"category":"drone","bbox":[50,20,10,10],"recognitionStatus":"PR"}]}
            (pred/"i000000.json").write_text(json.dumps(prediction));(truth/"f000000.json").write_text(json.dumps(reference))
            result=compare(mapping,pred,truth)
            self.assertEqual((result["truePositives"],result["falsePositives"],result["falseNegatives"]),(1,1,1))
            self.assertEqual(result["byReferenceRecognitionStatus"]["R"]["matched"],1)
            mapping[0]["rgbPixelSha256"]="wrong"
            with self.assertRaises(ValueError):compare(mapping,pred,truth)


if __name__=="__main__":unittest.main()
