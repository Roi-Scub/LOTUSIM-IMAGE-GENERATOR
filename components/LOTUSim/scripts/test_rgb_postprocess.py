#!/usr/bin/env python3
"""No model, external service, annotation or pose is needed by RGB review."""

import copy
import math
from pathlib import Path
import sys
import unittest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from rgb_postprocess import postprocess_predictions, validate_settings


def pred(category="speedboat", score=0.8, box=None, **extra):
    return {"category": category, "score": score, "bbox": box or [20, 20, 20, 20], **extra}


class ReviewTests(unittest.TestCase):
    def test_cross_class_near_identical_boxes_keep_score_and_show_alternatives(self):
        original = [pred("buoy", 0.6), pred("container_ship", 0.4, [20.1, 20.1, 20, 20])]
        result = postprocess_predictions(original, 200, 100)
        self.assertEqual(len(result["predictions"]), 1)
        kept = result["predictions"][0]
        self.assertEqual(
            (kept["category"], kept["score"], kept["bbox"]), ("buoy", 0.6, [20, 20, 20, 20])
        )
        self.assertTrue(kept["classAmbiguity"])
        self.assertEqual(kept["reviewStatus"], "uncertain")
        self.assertEqual(
            {p["category"] for p in kept["classAlternatives"]}, {"buoy", "container_ship"}
        )
        self.assertEqual(result["review"]["rejected"][0]["reason"], "duplicate_cross_class")
        self.assertEqual(
            result["review"]["counts"], {"input": 2, "retained": 0, "uncertain": 1, "rejected": 1}
        )

    def test_same_class_nms_preserves_strongest(self):
        result = postprocess_predictions(
            [pred(score=0.4), pred(score=0.9, box=[21, 21, 20, 20])], 200, 100
        )
        self.assertEqual([p["score"] for p in result["predictions"]], [0.9])
        self.assertEqual(result["review"]["rejected"][0]["reason"], "duplicate_same_class")

    def test_different_nearby_overlapping_objects_are_not_merged(self):
        result = postprocess_predictions(
            [pred("speedboat", box=[20, 20, 20, 20]), pred("sailboat", box=[24, 20, 20, 20])],
            200,
            100,
        )
        self.assertEqual(len(result["predictions"]), 2)
        self.assertEqual(result["review"]["duplicateGroups"], [])

    def test_small_real_object_inside_large_box_is_not_a_duplicate(self):
        result = postprocess_predictions(
            [pred("ferry", box=[10, 10, 100, 60]), pred("speedboat", box=[30, 30, 10, 10])],
            200,
            100,
        )
        self.assertEqual(len(result["predictions"]), 2)

    def test_legacy_containment_is_not_enough(self):
        result = postprocess_predictions(
            [pred(box=[20, 20, 40, 40]), pred(score=0.7, box=[25, 25, 30, 30])], 200, 200
        )
        # IoU=.5625 is same-class NMS; change to a ratio below its threshold.
        self.assertEqual(len(result["predictions"]), 1)
        result = postprocess_predictions(
            [pred(box=[20, 20, 40, 40]), pred(score=0.7, box=[26, 26, 28, 28])], 200, 200
        )
        self.assertEqual(len(result["predictions"]), 2)

    def test_provenance_and_close_center_can_identify_tile_fragment(self):
        first = pred(
            "speedboat",
            0.8,
            [20, 20, 40, 40],
            sourceRegion=[0, 0, 100, 100],
            regionIndex=1,
            touchesSourceBoundary=False,
        )
        second = pred(
            "motor_yacht",
            0.7,
            [26, 26, 28, 28],
            sourceRegion=[10, 10, 110, 110],
            regionIndex=2,
            touchesSourceBoundary=True,
        )
        # Area ratio .49 is too small; use 29x29 (.5256), IoU below .55.
        second["bbox"] = [25.5, 25.5, 29, 29]
        result = postprocess_predictions([first, second], 200, 200)
        self.assertEqual(len(result["predictions"]), 1)
        self.assertEqual(result["review"]["rejected"][0]["reason"], "duplicate_tile_fragment")
        self.assertEqual(result["predictions"][0]["bbox"], first["bbox"])

    def test_fragment_requires_edge_and_actual_distinct_regions(self):
        first = pred(
            "speedboat", 0.8, [20, 20, 40, 40], sourceRegion=[0, 0, 100, 100], regionIndex=1
        )
        second = pred(
            "motor_yacht", 0.7, [25.5, 25.5, 29, 29], sourceRegion=[10, 10, 110, 110], regionIndex=2
        )
        self.assertEqual(len(postprocess_predictions([first, second], 200, 200)["predictions"]), 2)
        second["touchesSourceBoundary"] = True
        second["sourceRegion"] = first["sourceRegion"]
        self.assertEqual(len(postprocess_predictions([first, second], 200, 200)["predictions"]), 2)

    def test_unknown_family_is_not_resolved_from_text(self):
        first = pred(
            "speedboat",
            0.8,
            [20, 20, 40, 40],
            sourceRegion=[0, 0, 100, 100],
            regionIndex=1,
            touchesSourceBoundary=True,
        )
        second = pred(
            "unknown",
            0.7,
            [25.5, 25.5, 29, 29],
            sourceRegion=[10, 10, 110, 110],
            regionIndex=2,
            textLabel="a speedboat a drone",
        )
        self.assertEqual(len(postprocess_predictions([first, second], 200, 200)["predictions"]), 2)

    def test_roi_center_inside_rejected_and_original_preserved(self):
        mask = Image.new("L", (200, 100))
        ImageDraw.Draw(mask).polygon([(0, 80), (80, 40), (100, 100), (0, 100)], fill=255)
        original = pred(box=[0, 80, 15, 15])
        result = postprocess_predictions([original], 200, 100, mask)
        rejection = result["review"]["rejected"][0]
        self.assertEqual(rejection["reason"], "excluded_center")
        self.assertEqual(rejection["prediction"], original)
        self.assertGreater(rejection["exclusionFraction"], 0.5)

    def test_roi_overlap_rejected_when_center_outside(self):
        mask = Image.new("L", (100, 100), 255)
        ImageDraw.Draw(mask).rectangle((40, 40, 60, 60), fill=0)
        result = postprocess_predictions([pred(box=[10, 10, 80, 80])], 100, 100, mask)
        self.assertEqual(result["review"]["rejected"][0]["reason"], "excluded_overlap")

    def test_partial_roi_overlap_does_not_clip_or_hide_sea_target(self):
        mask = Image.new("L", (200, 100))
        ImageDraw.Draw(mask).rectangle((0, 0, 29, 99), fill=255)
        original = pred(box=[20, 20, 50, 30])
        result = postprocess_predictions([original], 200, 100, mask)
        self.assertEqual(len(result["predictions"]), 1)
        kept = result["predictions"][0]
        self.assertEqual(kept["bbox"], original["bbox"])
        self.assertAlmostEqual(kept["exclusionFraction"], 0.2)
        self.assertFalse(kept["exclusionCenterInside"])

    def test_sparse_foreground_survives_exact_mask_even_when_bbox_center_is_excluded(self):
        mask = Image.new("L", (200, 100), 255)
        # A thin foreground silhouette occupies little of its rectangle; the
        # rectangle's center can legitimately be observer background.
        ImageDraw.Draw(mask).rectangle((15, 15, 15, 34), fill=0)
        original = pred("bird", 0.9, [10, 10, 40, 40])
        result = postprocess_predictions(
            [original],
            200,
            100,
            mask,
            {"rejectExcludedCenter": False, "maskOverlapThreshold": 0.995},
        )
        self.assertEqual(len(result["predictions"]), 1)
        kept = result["predictions"][0]
        self.assertTrue(kept["exclusionCenterInside"])
        self.assertGreater(kept["exclusionFraction"], 0.5)
        self.assertLess(kept["exclusionFraction"], 0.995)
        self.assertEqual(kept["bbox"], original["bbox"])
        self.assertEqual(result["review"]["counts"]["rejected"], 0)
        # Legacy/manual polygon behavior still rejects an excluded center.
        legacy = postprocess_predictions([original], 200, 100, mask)
        self.assertEqual(legacy["review"]["rejected"][0]["reason"], "excluded_center")

    def test_fully_excluded_box_is_rejected_without_center_rule(self):
        result = postprocess_predictions(
            [pred()],
            200,
            100,
            Image.new("L", (200, 100), 255),
            {"rejectExcludedCenter": False, "maskOverlapThreshold": 0.995},
        )
        self.assertEqual(result["predictions"], [])
        self.assertEqual(result["review"]["rejected"][0]["reason"], "excluded_overlap")
        self.assertEqual(result["review"]["rejected"][0]["exclusionFraction"], 1)

    def test_large_weak_box_is_uncertain_not_rejected(self):
        result = postprocess_predictions([pred(score=0.4, box=[0, 0, 100, 60])], 200, 100)
        self.assertEqual(result["review"]["counts"]["rejected"], 0)
        self.assertEqual(result["predictions"][0]["reviewReasons"], ["large_weak_proposal"])

    def test_tiny_native_pixels_and_unknowns_are_explicit(self):
        result = postprocess_predictions(
            [pred(box=[5, 5, 2, 2]), pred("unknown", box=[80, 20, 10, 10])], 200, 100
        )
        self.assertEqual(result["review"]["counts"]["uncertain"], 2)
        self.assertIn("insufficient_native_pixels", result["predictions"][0]["reviewReasons"])
        self.assertIn("ambiguous_or_unrecognizable", result["predictions"][1]["reviewReasons"])

    def test_semantic_conflict_alone_never_gates(self):
        result = postprocess_predictions([pred(semanticConflict=True)], 200, 100)
        self.assertEqual(result["predictions"][0]["reviewStatus"], "retained")

    def test_input_and_mask_are_never_mutated(self):
        original = [
            pred(score=0.4),
            pred(score=0.8),
            pred("ferry", score=0.6, box=[21, 20, 20, 20]),
        ]
        snapshot = copy.deepcopy(original)
        mask = Image.new("L", (200, 100), 127)
        pixels = mask.tobytes()
        postprocess_predictions(original, 200, 100, mask)
        self.assertEqual(original, snapshot)
        self.assertEqual(mask.tobytes(), pixels)

    def test_masks_dimensions_and_types_checked(self):
        with self.assertRaisesRegex(ValueError, "dimensions"):
            postprocess_predictions([], 200, 100, Image.new("L", (100, 100)))
        with self.assertRaises(ValueError):
            postprocess_predictions([], 200, 100, [])

    def test_settings_are_finite_known_and_positive_where_needed(self):
        self.assertEqual(validate_settings()["sameClassIou"], 0.55)
        self.assertEqual(validate_settings({"sameClassIou": 0.6})["sameClassIou"], 0.6)
        for settings in [
            {"unknown": 1},
            {"sameClassIou": math.nan},
            {"sameClassIou": True},
            {"maskOverlapThreshold": 0},
            {"minNativePixels": 0},
            {"minNativeSide": 1.5},
            {"largeMaxScore": 1.1},
            {"fragmentMaxCenterDistance": -1},
            {"rejectExcludedCenter": 1},
            {"rejectExcludedCenter": "false"},
        ]:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                validate_settings(settings)

    def test_invalid_predictions_fail_explicitly(self):
        for proposal in [
            pred(score=math.inf),
            pred(score=True),
            pred(box=[0, 0, -1, 2]),
            pred(box=[0, 0, math.nan, 2]),
        ]:
            with self.assertRaises(ValueError):
                postprocess_predictions([proposal], 200, 100)
        for size in [(True, 100), (200, 0), (200, 100.5)]:
            with self.assertRaises(ValueError):
                postprocess_predictions([], *size)

    def test_empty_predictions_and_empty_mask_are_valid(self):
        result = postprocess_predictions([], 200, 100, Image.new("L", (200, 100)))
        self.assertEqual(
            result["review"]["counts"], {"input": 0, "retained": 0, "uncertain": 0, "rejected": 0}
        )

    def test_counts_partition_input_and_audit_all_rejected_proposals(self):
        original = [
            pred(score=0.9),
            pred(score=0.8),
            pred("unknown", box=[80, 20, 10, 10]),
            pred(box=[180, 80, 10, 10]),
        ]
        mask = Image.new("L", (200, 100))
        ImageDraw.Draw(mask).rectangle((175, 75, 199, 99), fill=255)
        result = postprocess_predictions(original, 200, 100, mask)
        counts = result["review"]["counts"]
        self.assertEqual(
            counts["input"], sum(counts[key] for key in ["retained", "uncertain", "rejected"])
        )
        self.assertEqual(len(result["predictions"]), counts["retained"] + counts["uncertain"])
        indices = {entry["originalIndex"] for entry in result["review"]["rejected"]}
        indices |= {entry["reviewOriginalIndex"] for entry in result["predictions"]}
        self.assertEqual(indices, set(range(len(original))))


if __name__ == "__main__":
    unittest.main()
