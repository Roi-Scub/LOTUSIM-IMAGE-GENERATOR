"""Deterministic tests for honest calibration and split isolation; no ML deps."""

import json
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from rgb_confidence import (BIN_EDGES, CALIBRATION_TARGET, estimate_confidence,
                            fit_calibration, validate_disjoint_splits,
                            validate_split_isolation, wilson_interval)


DETECTOR = {"model": "test", "weightsSha256": "a", "tileSize": 512, "boxThreshold": .3}
KNOWLEDGE = {"contentSha256": "b"}


def records(number=20, correct=10, score=.9, category="buoy", group="calibration"):
    return [{"score": score, "correct": i < correct, "category": category,
             "sceneGroup": f"{group}-{i}", "imageHash": f"{group}-pixels-{i}"}
            for i in range(number)]


class CalibrationTests(unittest.TestCase):
    def estimate(self, calibration, score=.9, category="buoy", **kwargs):
        return estimate_confidence(score, category, calibration,
                                   kwargs.get("detector", DETECTOR),
                                   kwargs.get("knowledge", KNOWLEDGE))

    def test_unsupported_score_does_not_become_certainty(self):
        calibration = fit_calibration(records(19), DETECTOR, KNOWLEDGE)
        result = self.estimate(calibration)
        self.assertEqual(result["status"], "insufficient_support")
        self.assertIsNone(result["calibratedConfidencePercent"])
        self.assertIsNone(result["confidenceIntervalPercent"])

    def test_twenty_predictions_ten_correct(self):
        calibration = fit_calibration(records(), DETECTOR, KNOWLEDGE)
        result = self.estimate(calibration)
        self.assertEqual(result["calibratedConfidencePercent"], 50)
        self.assertEqual(result["support"], 20)
        self.assertEqual(result["correctCount"], 10)
        self.assertEqual(result["calibrationTarget"], CALIBRATION_TARGET)
        low, high = result["confidenceIntervalPercent"]
        self.assertAlmostEqual(low, 29.9294, places=3)
        self.assertAlmostEqual(high, 70.0706, places=3)

    def test_false_positives_are_kept(self):
        result = self.estimate(fit_calibration(records(correct=0), DETECTOR, KNOWLEDGE))
        self.assertEqual(result["calibratedConfidencePercent"], 0)
        self.assertGreater(result["confidenceIntervalPercent"][1], 0)

    def test_all_correct_is_sample_precision_not_exact_probability(self):
        result = self.estimate(fit_calibration(records(correct=20), DETECTOR, KNOWLEDGE))
        self.assertEqual(result["calibratedConfidencePercent"], 100)
        self.assertLess(result["confidenceIntervalPercent"][0], 100)
        self.assertIn("not exact probability", result["reference"])

    def test_no_calibration(self):
        result = self.estimate(None)
        self.assertEqual(result["status"], "no_calibration")
        self.assertIsNone(result["calibratedConfidencePercent"])

    def test_empty_records_insufficient(self):
        result = self.estimate(fit_calibration([], DETECTOR, KNOWLEDGE))
        self.assertEqual(result["status"], "insufficient_support")

    def test_fixed_bin_boundaries(self):
        values = [0, .199999999, .2, .4, .6, .8, 1]
        data = [dict(records(1)[0], score=value) for value in values]
        calibration = fit_calibration(data, DETECTOR, KNOWLEDGE)
        self.assertEqual(calibration["binEdges"], list(BIN_EDGES))
        self.assertEqual([b["support"] for b in calibration["pooled"]], [2, 1, 1, 1, 2])

    def test_support_is_per_bin_not_global(self):
        data = records(20, 10, .5) + records(1, 1, .9)
        result = self.estimate(fit_calibration(data, DETECTOR, KNOWLEDGE))
        self.assertEqual(result["status"], "insufficient_support")
        self.assertEqual(result["support"], 1)

    def test_category_fallback_to_pool_is_explicit(self):
        data = records(10, 10, category="buoy") + records(10, 0, category="bird")
        result = self.estimate(fit_calibration(data, DETECTOR, KNOWLEDGE))
        self.assertEqual(result["calibratedConfidencePercent"], 50)
        self.assertEqual(result["status"], "pooled_empirical_precision")
        self.assertEqual(result["calibrationScope"], "pooled")

    def test_category_has_priority_when_supported(self):
        data = records(20, 5) + records(20, 20, category="bird")
        result = self.estimate(fit_calibration(data, DETECTOR, KNOWLEDGE))
        self.assertEqual(result["calibratedConfidencePercent"], 25)
        self.assertEqual(result["calibrationScope"], "category")

    def test_changed_detector_or_knowledge_or_missing_signature(self):
        calibration = fit_calibration(records(), DETECTOR, KNOWLEDGE)
        for detector, knowledge in [(dict(DETECTOR, tileSize=0), KNOWLEDGE),
                                    (DETECTOR, "changed"), (None, KNOWLEDGE),
                                    (DETECTOR, None)]:
            result = self.estimate(calibration, detector=detector, knowledge=knowledge)
            self.assertEqual(result["status"], "signature_mismatch")
            self.assertIsNone(result["calibratedConfidencePercent"])

    def test_signature_json_order_is_not_a_change(self):
        calibration = fit_calibration(records(), DETECTOR, KNOWLEDGE)
        detector = dict(reversed(list(DETECTOR.items())))
        self.assertEqual(self.estimate(calibration, detector=detector)["status"],
                         "empirical_precision")

    def test_optional_knowledge_signature(self):
        calibration = fit_calibration(records(), DETECTOR)
        result = estimate_confidence(.9, "buoy", calibration, DETECTOR)
        self.assertEqual(result["status"], "empirical_precision")

    def test_nonfinite_and_out_of_range_scores_rejected(self):
        for score in [-.1, 1.1, float("nan"), float("inf"), -float("inf"), True, "0.9"]:
            with self.subTest(score=score):
                with self.assertRaises(ValueError):
                    fit_calibration([dict(records(1)[0], score=score)], DETECTOR)
                with self.assertRaises(ValueError):
                    estimate_confidence(score, "buoy", None)

    def test_nonboolean_correct_rejected(self):
        for correct in [1, 0, "yes", None]:
            with self.assertRaises(ValueError):
                fit_calibration([dict(records(1)[0], correct=correct)], DETECTOR)

    def test_missing_lineage_rejected(self):
        for key in ["category", "sceneGroup", "imageHash", "score", "correct"]:
            record = records(1)[0]
            del record[key]
            with self.assertRaises(ValueError):
                fit_calibration([record], DETECTOR)

    def test_oracle_source_rejected(self):
        for source in ["ground_truth_crop", "oracle box", "gt_crop"]:
            with self.assertRaises(ValueError):
                fit_calibration([dict(records(1)[0], source=source)], DETECTOR)

    def test_bad_minimum_or_signature_rejected(self):
        for minimum in [0, -1, .5, True]:
            with self.assertRaises(ValueError):
                fit_calibration([], DETECTOR, min_support=minimum)
        for signature in [None, "", {}, [], {"bad": math.nan}]:
            with self.assertRaises(ValueError):
                fit_calibration([], signature)

    def test_json_roundtrip_and_tampered_counts(self):
        calibration = json.loads(json.dumps(fit_calibration(records(), DETECTOR, KNOWLEDGE)))
        self.assertEqual(self.estimate(calibration)["calibratedConfidencePercent"], 50)
        calibration["categories"]["buoy"][4]["correct"] = 21
        self.assertEqual(self.estimate(calibration)["status"], "invalid_calibration")

    def test_bad_schema_or_edges(self):
        calibration = fit_calibration(records(), DETECTOR, KNOWLEDGE)
        for key, value in [("schema", "different"), ("binEdges", [0, 1])]:
            self.assertEqual(self.estimate(dict(calibration, **{key: value}))["status"],
                             "invalid_calibration")

    def test_wilson_invalid_counts(self):
        self.assertIsNone(wilson_interval(0, 0))
        for correct, count in [(-1, 1), (2, 1), (1, -1), (True, 1), (1, 1.5)]:
            with self.assertRaises(ValueError):
                wilson_interval(correct, count)


class SplitTests(unittest.TestCase):
    def test_disjoint_scene_and_pixel_groups_pass(self):
        result = validate_disjoint_splits(records(group="calibration"),
                                          records(group="test"),
                                          records(group="knowledge"))
        self.assertTrue(result["passed"])
        self.assertEqual(result["splits"]["test"]["imageHashes"], 20)

    def test_same_group_different_pixels_rejected(self):
        with self.assertRaisesRegex(ValueError, "sceneGroup"):
            validate_split_isolation({"calibration": [{"sceneGroup": "same", "imageHash": "a"}],
                                      "test": [{"sceneGroup": "same", "imageHash": "b"}]})

    def test_different_group_same_pixels_rejected(self):
        with self.assertRaisesRegex(ValueError, "imageHash"):
            validate_split_isolation({"calibration": [{"sceneGroup": "a", "imageHash": "same"}],
                                      "test": [{"sceneGroup": "b", "imageHash": "same"}]})

    def test_knowledge_overlap_rejected(self):
        with self.assertRaises(ValueError):
            validate_disjoint_splits(records(group="calibration"), records(group="test"),
                                     records(group="test"))

    def test_multiple_predictions_per_image_inside_one_split_allowed(self):
        result = validate_split_isolation({"calibration": records() + records()})
        self.assertEqual(result["splits"]["calibration"]["records"], 40)
        self.assertEqual(result["splits"]["calibration"]["imageHashes"], 20)

    def test_missing_group_or_hash_rejected(self):
        for record in [{"sceneGroup": "a"}, {"imageHash": "a"}, None]:
            with self.assertRaises(ValueError):
                validate_split_isolation({"test": [record]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
