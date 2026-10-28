#!/usr/bin/env python3
"""Coordinator regression tests; fake inference only, no model/Gazebo/services."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import rgb_observer as coordinator
import rgb_validate
from rgb_confidence import fit_calibration, validate_split_isolation
from rgb_observer_worker import atomic_json, detector_signature


CONFIG = {
    "schema": "lotusim-rgb-observer-config-1", "model": "local-test-model",
    "revision": "a" * 40, "weightsSha256": "b" * 64,
    "modelDirectory": "not-loaded", "license": "test", "device": "cpu",
    "boxThreshold": .3, "textThreshold": .25, "nmsIou": .55, "tileSize": 0,
    "categories": [{"category": "buoy", "displayName": "bouée", "query": "a buoy"}]
}


class PipelineTests(unittest.TestCase):
    def source(self, root, count=1, seed=None):
        campaign = root / "campaign"
        (campaign / "rgb").mkdir(parents=True)
        for index in range(count):
            Image.new("RGB", (32, 24), (20+index, 50, 70)).save(campaign / "rgb" / f"f{index:06d}.png")
        if seed is not None:
            atomic_json(campaign / "requested-config.json", {"seed": seed})
        return campaign

    def config(self, root):
        path = root / "detector.json"
        atomic_json(path, CONFIG)
        return path

    def fake_infer(self, command, **kwargs):
        self.assertNotIn("--truth", command)
        rgb = Path(command[command.index("--rgb")+1])
        output = Path(command[command.index("--output")+1])
        output.mkdir()
        for path in sorted(rgb.glob("*.png")):
            self.assertRegex(path.name, r"^i[0-9]{6}\.png$")
            with Image.open(path) as image:
                digest = coordinator.pixel_hash(image)
            atomic_json(output / (path.stem + ".json"), {
                "rgbPixelSha256": digest, "predictions": []})
        atomic_json(output / "manifest.json", {"detectorSignature": "fake", "knowledgeSignature": None})
        return SimpleNamespace(returncode=0)

    def test_stage_uniform_neutral_names_and_clean_rgb(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); campaign = self.source(root, count=5, seed=42)
            (campaign / "overlays").mkdir()
            Image.new("RGB", (32, 24), "red").save(campaign / "overlays/f000000.png")
            output = root / "result"; output.mkdir()
            mapping = coordinator.stage(campaign / "rgb", output, limit=3, sampling="uniform")
            self.assertEqual([item["sourceImage"] for item in mapping], ["f000000.png", "f000002.png", "f000004.png"])
            self.assertEqual([item["workerImage"] for item in mapping], ["i000000.png", "i000001.png", "i000002.png"])
            self.assertEqual({item["sceneGroup"] for item in mapping}, {"lotusim-seed:42"})
            with Image.open(output / "input/rgb/i000000.png") as staged:
                self.assertEqual(staged.getpixel((0, 0)), (20, 50, 70))
            self.assertFalse((output / "input/annotations").exists())
            with self.assertRaises(ValueError):
                coordinator.stage(campaign / "overlays", root / "bad")

    def test_compare_coco_fallback_and_class_aware_matching(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); campaign = self.source(root)
            atomic_json(campaign / "annotations.coco.json", {
                "images": [{"id": 1, "width": 32, "height": 24, "file_name": "rgb/f000000.png"}],
                "categories": [{"id": 1, "name": "buoy"}],
                "annotations": [{"image_id": 1, "category_id": 1, "bbox": [1, 2, 12, 10], "area": 100}]})
            output = root / "result"; output.mkdir()
            mapping = coordinator.stage(campaign / "rgb", output)
            predictions = output / "predictions"; predictions.mkdir()
            atomic_json(predictions / "i000000.json", {"rgbPixelSha256": mapping[0]["rgbPixelSha256"],
                "predictions": [{"category": "buoy", "score": .9, "bbox": [1, 2, 12, 10]},
                                {"category": "drone", "score": .8, "bbox": [1, 2, 12, 10]}]})
            report = coordinator.compare(mapping, predictions, campaign / "annotations")
            self.assertEqual((report["truePositives"], report["falsePositives"], report["falseNegatives"]), (1, 1, 0))
            self.assertEqual(report["byVisiblePixelSize"]["32_to_255_pixels"], {"referenceObjects": 1, "matched": 1})
            self.assertEqual(report["calibrationRecords"][0]["localizationSource"], "independent_rgb_detector")
            self.assertEqual(report["frames"][0]["falsePositiveDiagnostics"][0]["nearestReferenceClass"], "buoy")

    def test_legacy_single_buoy_sidecar_uses_coco_dimensions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); campaign = self.source(root)
            (campaign / "annotations").mkdir()
            atomic_json(campaign / "annotations/f000000.json", {
                "schema": "lotusim-instance-geometry-1", "category": "buoy",
                "annotationPresent": True, "bbox": [1, 2, 12, 10], "visiblePixels": 91})
            atomic_json(campaign / "annotations.coco.json", {
                "images": [{"id": 1, "width": 32, "height": 24, "file_name": "rgb/f000000.png"}],
                "categories": [], "annotations": []})
            output = root / "result"; output.mkdir()
            mapping = coordinator.stage(campaign / "rgb", output)
            reference = coordinator.references(campaign / "annotations", mapping)["f000000.png"]
            self.assertEqual((reference["width"], reference["height"]), (32, 24))
            self.assertEqual(reference["annotations"][0]["visiblePixels"], 91)
            atomic_json(campaign / "annotations/f000000.json", {
                "schema": "lotusim-instance-geometry-1", "annotationPresent": False})
            reference = coordinator.references(campaign / "annotations", mapping)["f000000.png"]
            self.assertEqual(reference["annotations"], [])

    def test_missing_reference_is_not_an_empty_negative_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); campaign = self.source(root)
            output = root / "result"; output.mkdir()
            mapping = coordinator.stage(campaign / "rgb", output)
            predictions = output / "predictions"; predictions.mkdir()
            atomic_json(predictions / "i000000.json", {"rgbPixelSha256": mapping[0]["rgbPixelSha256"],
                "predictions": [{"category": "buoy", "score": .9, "bbox": [1, 2, 12, 10]}]})
            report = coordinator.compare(mapping, predictions, campaign / "annotations")
            self.assertEqual(report["missingReferenceImages"], ["f000000.png"])
            self.assertEqual(report["falsePositives"], 0)
            self.assertEqual(report["calibrationRecords"], [])
            self.assertIsNone(report["precision"])

    def test_pixel_hash_and_reference_dimensions_must_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); campaign = self.source(root)
            (campaign / "annotations").mkdir()
            atomic_json(campaign / "annotations/f000000.json", {"width": 100, "height": 80, "annotations": []})
            output = root / "result"; output.mkdir()
            mapping = coordinator.stage(campaign / "rgb", output)
            predictions = output / "predictions"; predictions.mkdir()
            atomic_json(predictions / "i000000.json", {"rgbPixelSha256": "wrong", "predictions": []})
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                coordinator.compare(mapping, predictions, campaign / "annotations")
            atomic_json(predictions / "i000000.json", {"rgbPixelSha256": mapping[0]["rgbPixelSha256"], "predictions": []})
            with self.assertRaisesRegex(ValueError, "dimensions differ"):
                coordinator.compare(mapping, predictions, campaign / "annotations")

    def test_gazebo_failure_falls_back_explicitly_and_missing_refs_remain_optional(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); campaign = self.source(root)
            fake_transport = SimpleNamespace(roundtrip=mock.Mock(side_effect=OSError("Docker not available")))
            output = root / "result"
            with mock.patch.dict(sys.modules, {"rgb_gazebo": fake_transport}), \
                    mock.patch.object(coordinator.subprocess, "run", side_effect=self.fake_infer):
                coordinator.run(campaign / "rgb", output, self.config(root), evaluate=True,
                                via_gazebo=True, plan_path=root / "no-plan.json")
            transport = json.loads((output / "transport-status.json").read_text())
            self.assertTrue(transport["fallback"])
            self.assertEqual(transport["used"], "direct_rgb")
            self.assertFalse((output / "comparison.json").exists())
            self.assertEqual(json.loads((output / "status.json").read_text())["status"], "complete")
            self.assertIn("Aucune annotation", (output / "index.html").read_text())

    def test_strict_gazebo_failure_does_not_start_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); campaign = self.source(root)
            fake_transport = SimpleNamespace(roundtrip=mock.Mock(side_effect=OSError("unavailable")))
            output = root / "result"
            with mock.patch.dict(sys.modules, {"rgb_gazebo": fake_transport}), \
                    mock.patch.object(coordinator.subprocess, "run") as worker:
                with self.assertRaises(OSError):
                    coordinator.run(campaign / "rgb", output, self.config(root), via_gazebo=True,
                                    strict_transport=True, plan_path=root / "no-plan.json")
            worker.assert_not_called()
            self.assertEqual(json.loads((output / "status.json").read_text())["status"], "failed")

    def test_missing_gazebo_module_can_fall_back_without_invented_transport_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); campaign = self.source(root)
            output = root / "result"
            real_import = __import__
            def unavailable(name, *args, **kwargs):
                if name == "rgb_gazebo":
                    raise ImportError("Gazebo Python relay is not installed")
                return real_import(name, *args, **kwargs)
            with mock.patch("builtins.__import__", side_effect=unavailable), \
                    mock.patch.object(coordinator.subprocess, "run", side_effect=self.fake_infer):
                coordinator.run(campaign / "rgb", output, self.config(root), via_gazebo=True,
                                plan_path=root / "no-plan.json")
            transport = json.loads((output / "transport-status.json").read_text())
            self.assertTrue(transport["fallback"])
            self.assertEqual(transport["used"], "direct_rgb")
            self.assertIn("not installed", transport["error"])

    def test_detector_signature_changes_settings_but_not_installation_path(self):
        config = copy.deepcopy(CONFIG)
        baseline = detector_signature(config)
        config["modelDirectory"] = "/another/local/path"
        self.assertEqual(detector_signature(config), baseline)
        config["tileSize"] = 1024
        self.assertNotEqual(detector_signature(config), baseline)
        config["tileSize"] = 0
        config["categories"][0]["query"] = "a navigation buoy"
        self.assertNotEqual(detector_signature(config), baseline)

    def test_same_seed_knowledge_and_test_are_not_independent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); campaign = self.source(root, count=2, seed=42)
            knowledge = root / "knowledge"
            (knowledge / "coordinator").mkdir(parents=True)
            with Image.open(campaign / "rgb/f000000.png") as image:
                image_hash = coordinator.pixel_hash(image)
            atomic_json(knowledge / "coordinator/provenance.json", {"frames": [{
                "path": str(campaign / "rgb/f000000.png"), "group": str(campaign),
                "rgbPixelSha256": image_hash}]})
            other_output = root / "test"; other_output.mkdir()
            mapping = coordinator.stage(campaign / "rgb", other_output)
            test_records = [{"sceneGroup": mapping[1]["sceneGroup"], "imageHash": mapping[1]["rgbPixelSha256"]}]
            with self.assertRaisesRegex(ValueError, "leakage"):
                validate_split_isolation({"knowledge": coordinator.knowledge_frames(knowledge), "test": test_records})

    def test_calibration_preserves_frames_with_no_predictions_for_isolation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); run = root / "run"
            (run / "predictions").mkdir(parents=True)
            atomic_json(run / "run-manifest.json", {"role": "calibration",
                "sceneGroups": ["calibration-empty-scene"], "imageHashes": ["empty-frame-hash"]})
            atomic_json(run / "input-map.json", [{"sceneGroup": "calibration-empty-scene",
                "rgbPixelSha256": "empty-frame-hash"}])
            atomic_json(run / "predictions/manifest.json", {"detectorSignature": "test-detector", "knowledgeSignature": None})
            atomic_json(run / "calibration-records.json", {"role": "calibration", "records": []})
            output = root / "calibration.json"
            rgb_validate.calibrate(SimpleNamespace(run=[run], knowledge=None, min_support=20, output=output))
            payload = json.loads(output.read_text())
            self.assertIn("calibration-empty-scene", payload["sceneGroups"])
            self.assertIn("empty-frame-hash", payload["imageHashes"])

    def test_incomplete_or_mixed_signature_runs_cannot_fit_calibration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folders = []
            for index in range(2):
                run = root / str(index); (run / "predictions").mkdir(parents=True)
                atomic_json(run / "run-manifest.json", {"role": "calibration"})
                atomic_json(run / "predictions/manifest.json", {"detectorSignature": f"different-{index}",
                    "knowledgeSignature": None, "coverageLimited": False})
                atomic_json(run / "calibration-records.json", {"records": []})
                atomic_json(run / "input-map.json", [{"sceneGroup": f"scene-{index}",
                    "rgbPixelSha256": f"image-{index}"}])
                folders.append(run)
            arguments = SimpleNamespace(run=folders, knowledge=None, min_support=20, output=root / "calibration.json")
            with self.assertRaisesRegex(ValueError, "identical"):
                rgb_validate.calibrate(arguments)
            atomic_json(folders[0] / "predictions/manifest.json", {"detectorSignature": "d", "coverageLimited": True})
            arguments.run = folders[:1]
            with self.assertRaisesRegex(ValueError, "coverage"):
                rgb_validate.calibrate(arguments)


if __name__ == "__main__":
    unittest.main()
