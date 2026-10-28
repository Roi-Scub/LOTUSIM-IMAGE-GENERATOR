"""Localized visual verifier helper tests: no real model or network."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from rgb_verify_instances import MODE, classify_crop, crop_box, evaluate_instances


class Image:
    def __init__(self, width=30, height=20):
        self.width, self.height = width, height


class Knowledge:
    def __init__(self, category="buoy", similarity=0.8, margin=0.1):
        self.category, self.similarity, self.margin = category, similarity, margin
        self.calls = []

    def query(self, image, encoder, k):
        self.calls.append((image, encoder, k))
        return {
            "topCategory": self.category,
            "similarity": self.similarity,
            "margin": self.margin,
            "neighbors": [
                {
                    "category": self.category,
                    "similarity": self.similarity,
                    "crop": "crops/e000000.png",
                }
            ],
        }


class ClassifyTests(unittest.TestCase):
    def test_clear_class_is_suggestion_not_probability(self):
        image, encoder, knowledge = Image(), object(), Knowledge()
        result = classify_crop(image, knowledge, encoder)
        self.assertEqual(result["category"], "buoy")
        self.assertEqual(result["decision"], "visual_suggestion")
        self.assertFalse(result["probabilityCalibrated"])
        self.assertIsNone(result["calibratedConfidencePercent"])
        self.assertEqual(knowledge.calls, [(image, encoder, 3)])

    def test_tiny_crop_never_queries_encoder(self):
        for image in [Image(2, 10), Image(4, 7), Image(30, 3)]:
            knowledge = Knowledge()
            result = classify_crop(image, knowledge, None)
            self.assertEqual(result["decision"], "indeterminate")
            self.assertEqual(knowledge.calls, [])

    def test_native_size_boundary(self):
        self.assertEqual(classify_crop(Image(4, 8), Knowledge(), None)["category"], "buoy")

    def test_small_margin_abstains(self):
        result = classify_crop(Image(), Knowledge(margin=0.029), None)
        self.assertEqual(result["category"], "unknown")
        self.assertEqual(result["decisionReason"], "ambiguous_visual_neighbors")

    def test_exact_margin_boundary_accepts(self):
        self.assertEqual(classify_crop(Image(), Knowledge(margin=0.03), None)["category"], "buoy")

    def test_no_diverse_class_or_nan_abstains(self):
        for knowledge in [
            Knowledge(margin=None),
            Knowledge(margin=float("nan")),
            Knowledge(similarity=float("inf")),
            Knowledge(category="unknown"),
        ]:
            self.assertEqual(classify_crop(Image(), knowledge, None)["category"], "unknown")

    def test_invalid_margin_threshold(self):
        for margin in [-1, float("nan"), True, 2.1]:
            with self.assertRaises(ValueError):
                classify_crop(Image(), Knowledge(), None, margin)


class GeometryTests(unittest.TestCase):
    def test_crop_is_clipped_to_native_image(self):
        self.assertEqual(crop_box([-2, 3.1, 8, 20], 10, 10), (0, 3, 6, 10))

    def test_invalid_or_outside_geometry_rejected(self):
        for bbox in [
            [],
            [0, 0, 0, 1],
            [0, 0, 1, -1],
            [20, 20, 1, 1],
            [0, 0, float("nan"), 1],
            [False, 0, 1, 1],
        ]:
            with self.assertRaises(ValueError):
                crop_box(bbox, 10, 10)


class EvaluationTests(unittest.TestCase):
    def record(self, crop="c000000.png", expected="buoy", visible=100):
        return {"workerCrop": crop, "expectedCategory": expected, "visiblePixels": visible}

    def test_evaluator_adds_class_only_after_rgb_classification(self):
        prediction = classify_crop(Image(), Knowledge(), None)
        self.assertNotIn("expectedCategory", prediction)
        report = evaluate_instances([self.record()], {"c000000.png": prediction})
        self.assertEqual(report["correctDecidedInstances"], 1)
        self.assertEqual(report["accuracyOnDecidedInstances"], 1)
        self.assertFalse(report["detectorMetricsApplicable"])
        self.assertFalse(report["calibrationApplicable"])
        self.assertNotIn("iou", json.dumps(report).lower())
        self.assertNotIn("precision", report)

    def test_visible_mask_small_but_bbox_large_abstains_post_inference(self):
        prediction = classify_crop(Image(), Knowledge(), None)
        report = evaluate_instances([self.record(visible=2)], {"c000000.png": prediction})
        self.assertEqual(report["indeterminateInstances"], 1)
        self.assertIsNone(report["accuracyOnDecidedInstances"])
        self.assertIsNone(report["rows"][0]["evaluator"]["correct"])
        self.assertEqual(
            prediction["category"], "buoy"
        )  # Evaluation does not mutate the worker result.
        self.assertEqual(report["rows"][0]["rawClassification"]["category"], "buoy")
        self.assertEqual(report["rows"][0]["classification"]["category"], "unknown")
        self.assertEqual(report["rows"][0]["geometryQualityGate"]["status"], "rejected")
        self.assertFalse(report["rows"][0]["geometryQualityGate"]["isVisualInference"])
        self.assertEqual(report["geometryRejectedInstances"], 1)
        self.assertEqual(report["visualAbstentionInstances"], 0)

    def test_wrong_class_is_disagreement_not_false_detection(self):
        prediction = classify_crop(Image(), Knowledge(category="bird"), None)
        report = evaluate_instances([self.record()], {"c000000.png": prediction})
        self.assertEqual(report["accuracyOnDecidedInstances"], 0)
        self.assertEqual(report["decidedInstances"], 1)
        self.assertFalse(report["rows"][0]["evaluator"]["correct"])

    def test_missing_classification_and_wrong_mode_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_instances([self.record()], {})
        with self.assertRaises(ValueError):
            evaluate_instances([self.record()], {"c000000.png": {"mode": "detector"}})

    def test_invalid_visible_count_rejected(self):
        prediction = classify_crop(Image(), Knowledge(), None)
        for pixels in [-1, float("nan"), True]:
            with self.assertRaises(ValueError):
                evaluate_instances([self.record(visible=pixels)], {"c000000.png": prediction})

    def test_accuracy_excludes_abstentions(self):
        first = classify_crop(Image(), Knowledge(), None)
        second = classify_crop(Image(), Knowledge(margin=0.01), None)
        report = evaluate_instances(
            [self.record(), self.record("c000001.png")],
            {"c000000.png": first, "c000001.png": second},
        )
        self.assertEqual(report["accuracyOnDecidedInstances"], 1)
        self.assertEqual(report["abstentionRate"], 0.5)

    def test_missing_classes_are_evaluator_only_coverage_warning(self):
        prediction = classify_crop(Image(), Knowledge(category="bird"), None)
        report = evaluate_instances(
            [self.record()], {"c000000.png": prediction}, knowledge_categories={"bird", "drone"}
        )
        self.assertEqual(report["coveredKnowledgeClasses"], ["bird", "drone"])
        self.assertEqual(report["expectedClassesMissingFromKnowledge"], ["buoy"])
        self.assertTrue(report["rows"][0]["evaluator"]["unsupportedCategoryRisk"])
        self.assertNotIn("referenceCategory", report["rows"][0]["rawClassification"])

    def test_covered_class_and_unknown_coverage_are_distinct(self):
        prediction = classify_crop(Image(), Knowledge(), None)
        report = evaluate_instances([self.record()], {"c000000.png": prediction}, {"buoy"})
        self.assertEqual(report["expectedClassesMissingFromKnowledge"], [])
        self.assertFalse(report["rows"][0]["evaluator"]["unsupportedCategoryRisk"])
        unspecified = evaluate_instances([self.record()], {"c000000.png": prediction})
        self.assertIsNone(unspecified["expectedClassesMissingFromKnowledge"])
        self.assertFalse(unspecified["knowledgeCoverageAssessed"])

    def test_pure_visual_abstention_separated_from_geometry_rejection(self):
        prediction = classify_crop(Image(), Knowledge(margin=0.01), None)
        report = evaluate_instances([self.record()], {"c000000.png": prediction}, {"buoy"})
        self.assertEqual(report["visualAbstentionInstances"], 1)
        self.assertEqual(report["geometryRejectedInstances"], 0)
        self.assertEqual(report["rows"][0]["geometryQualityGate"]["status"], "passed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
