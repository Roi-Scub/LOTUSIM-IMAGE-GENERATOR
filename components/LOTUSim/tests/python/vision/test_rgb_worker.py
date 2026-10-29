#!/usr/bin/env python3
"""Worker geometry/abstention contract; no model, download or service required."""

import copy
import unittest

from lotusim_image_generator.vision.worker import (
    attach_evidence,
    category_for,
    clip_region_box,
    detector_signature,
    prepare_prediction,
    suppress,
    tile_regions,
    validate_config,
)


def config():
    return {
        "schema": "lotusim-rgb-observer-config-1",
        "model": "test/local",
        "revision": "a" * 40,
        "weightsSha256": "b" * 64,
        "modelDirectory": "/ignored/path",
        "license": "Apache-2.0",
        "device": "cpu",
        "boxThreshold": 0.3,
        "textThreshold": 0.25,
        "nmsIou": 0.55,
        "tileSize": 1024,
        "categories": [
            {"category": "buoy", "displayName": "bouée", "query": "a buoy"},
            {"category": "sailboat", "displayName": "voilier", "query": "a sailboat"},
        ],
    }


def prediction(category="buoy", box=None, score=0.9):
    return {
        "category": category,
        "displayName": "bouée",
        "textLabel": "a buoy",
        "bbox": [10, 10, 10, 10] if box is None else box,
        "score": score,
    }


class WorkerTests(unittest.TestCase):
    def test_class_aware_nms(self):
        values = [prediction(), prediction("sailboat", score=0.8), prediction(score=0.7)]
        self.assertEqual([p["category"] for p in suppress(values, 0.5)], ["buoy", "sailboat"])

    def test_legacy_nms_without_categories(self):
        values = [{"score": 0.9, "bbox": [0, 0, 10, 10]}, {"score": 0.8, "bbox": [1, 1, 10, 10]}]
        self.assertEqual(len(suppress(values, 0.5)), 1)

    def test_tile_edges_and_unique_full_frame(self):
        regions = tile_regions(3840, 2160, 1024)
        self.assertEqual(regions[0], (0, 0, 3840, 2160))
        self.assertIn((2816, 1136, 3840, 2160), regions)
        self.assertEqual(len(regions), len(set(regions)))
        for left, top, right, bottom in regions:
            self.assertTrue(0 <= left < right <= 3840)
            self.assertTrue(0 <= top < bottom <= 2160)

    def test_small_image_or_disabled_tiles(self):
        self.assertEqual(tile_regions(600, 400, 1024), [(0, 0, 600, 400)])
        self.assertEqual(tile_regions(3840, 2160, 0), [(0, 0, 3840, 2160)])
        self.assertIn((0, 976, 600, 2000), tile_regions(600, 2000, 1024))

    def test_overlap_changes_coverage(self):
        self.assertGreater(
            len(tile_regions(3000, 2000, 1000, 0.5)), len(tile_regions(3000, 2000, 1000, 0))
        )
        for overlap in (float("nan"), float("inf"), -1, 1, True):
            with self.subTest(overlap=overlap), self.assertRaises(ValueError):
                tile_regions(3000, 2000, 1000, overlap)

    def test_tile_boxes_clip_to_actual_evidence_not_unseen_neighbor(self):
        self.assertEqual(
            clip_region_box([-10, -20, 200, 300], (500, 600, 600, 700)), [500, 600, 100, 100]
        )
        self.assertEqual(clip_region_box([5, 6, 15, 20], (500, 600, 600, 700)), [505, 606, 10, 14])
        self.assertIsNone(clip_region_box([-20, 5, -10, 20], (500, 600, 600, 700)))
        self.assertIsNone(clip_region_box([0, 0, float("nan"), 20], (500, 600, 600, 700)))

    def test_legacy_configuration_defaults_valid(self):
        validate_config(config())

    def test_nonfinite_or_boolean_configuration_rejected(self):
        for field in ("boxThreshold", "textThreshold", "nmsIou", "tileOverlap"):
            for value in (float("nan"), float("inf"), True, "0.3"):
                candidate = config()
                candidate[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    validate_config(candidate)
        for field in ("minCropPixels", "minCropSide", "tileSize"):
            for value in (float("nan"), True, -1, 1.5):
                candidate = config()
                candidate[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    validate_config(candidate)

    def test_config_forbids_scene_metadata_and_duplicate_classes(self):
        candidate = config()
        candidate["poses"] = []
        with self.assertRaises(ValueError):
            validate_config(candidate)
        candidate = config()
        candidate["categories"].append(candidate["categories"][0])
        with self.assertRaises(ValueError):
            validate_config(candidate)

    def test_signature_stable_excludes_paths_and_resolves_defaults(self):
        first = config()
        second = copy.deepcopy(first)
        second.update(
            modelDirectory="another/location", tileOverlap=0.2, minCropPixels=32, minCropSide=4
        )
        second["categories"][0]["displayName"] = "another display name"
        self.assertEqual(detector_signature(first), detector_signature(second))
        second["tileOverlap"] = 0.3
        self.assertNotEqual(detector_signature(first), detector_signature(second))
        self.assertEqual(len(detector_signature(first)), 64)

    def test_ambiguous_labels_stay_unknown(self):
        self.assertEqual(
            category_for("a buoy a sailboat", config()["categories"])["category"], "unknown"
        )
        self.assertEqual(category_for("a buoy", config()["categories"])["category"], "buoy")

    def test_two_pixels_abstain_and_preserve_hypothesis(self):
        result = prepare_prediction(prediction(box=[0, 0, 2, 1]), config())
        self.assertEqual(result["category"], "unknown")
        self.assertEqual(result["hypothesisCategory"], "buoy")
        self.assertEqual(result["recognitionDecision"], "indeterminate")
        self.assertEqual(result["decisionReason"], "insufficient_native_pixels")
        self.assertIsNone(result["calibratedConfidencePercent"])
        self.assertFalse(result["confidenceCalibrated"])
        self.assertEqual(result["detectorScorePercent"], 90)

    def test_minimum_crop_side_and_area(self):
        for box in ([0, 0, 3, 100], [0, 0, 4, 7]):
            self.assertEqual(
                prepare_prediction(prediction(box=box), config())["category"], "unknown"
            )
        result = prepare_prediction(prediction(box=[0, 0, 4, 8]), config())
        self.assertEqual(result["category"], "buoy")
        self.assertEqual(result["recognitionDecision"], "hypothesis")
        self.assertIsNone(result["calibratedConfidencePercent"])

    def test_kb_disagreement_does_not_force_class_or_probability(self):
        from PIL import Image

        class Knowledge:
            def query(self, image, encoder, k):
                self.size = image.size
                return {
                    "topCategory": "sailboat",
                    "similarity": 0.99,
                    "neighbors": [],
                    "scoreMeaning": "cosine_similarity_not_probability",
                }

        knowledge = Knowledge()
        result = prepare_prediction(prediction(), config())
        attach_evidence(result, Image.new("RGB", (100, 100)), knowledge, object())
        self.assertEqual(knowledge.size, (10, 10))
        self.assertEqual(result["category"], "buoy")
        self.assertTrue(result["semanticConflict"])
        self.assertIsNone(result["calibratedConfidencePercent"])

    def test_tiny_crops_never_queried_against_knowledge(self):
        class Knowledge:
            def query(self, *args, **kwargs):
                self.fail("Tiny objects must not be enlarged into apparent evidence")

        result = prepare_prediction(prediction(box=[0, 0, 2, 1]), config())
        attach_evidence(result, None, Knowledge(), None)
        self.assertNotIn("semanticEvidence", result)

    def test_invalid_prediction_floats_rejected(self):
        for score in (float("nan"), float("inf"), 1.1, True):
            with self.subTest(score=score), self.assertRaises(ValueError):
                prepare_prediction(prediction(score=score), config())
        with self.assertRaises(ValueError):
            prepare_prediction(prediction(box=[0, 0, float("nan"), 1]), config())


if __name__ == "__main__":
    unittest.main()
