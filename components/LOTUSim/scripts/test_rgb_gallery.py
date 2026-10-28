#!/usr/bin/env python3
"""Offline gallery regressions: native coordinates, provenance and safe JSON."""

import copy
import json
import math
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from rgb_visual_gallery import build_gallery_data, render_gallery


def prediction(category="buoy", **updates):
    return {
        "category": category,
        "displayName": "bouée",
        "score": 0.61,
        "bbox": [100, 200, 20, 40],
        "recognitionDecision": "hypothesis",
        **updates,
    }


class GalleryTests(unittest.TestCase):
    def fixture(self, root, payload=None):
        (root / "predictions").mkdir()
        if payload is not None:
            (root / "predictions/i000000.json").write_text(json.dumps(payload))
        return [
            {
                "workerImage": "i000000.png",
                "sourceImage": "f000000.png",
                "width": 3840,
                "height": 2160,
            }
        ]

    def data_from_page(self, page):
        match = re.search(
            r'<script id="gallery-data" type="application/json">(.*?)</script>', page, re.S
        )
        self.assertIsNotNone(match)
        return json.loads(match.group(1))

    def test_raw_rgb_is_base_not_burned_in_overlay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mapping = self.fixture(root, {"predictions": [prediction()]})
            render_gallery(root, mapping)
            page = (root / "index.html").read_text()
            data = self.data_from_page(page)
            self.assertEqual(data["frames"][0]["raw"], "input/rgb/i000000.png")
            self.assertEqual(data["frames"][0]["retained"][0]["bbox"], [100, 200, 20, 40])
            self.assertNotIn("predictions/overlays/", page)
            self.assertIn('id="frameSelect"', page)
            self.assertIn('id="viewer"', page)
            self.assertNotIn('repeat(auto-fit', page)

    def test_uncertain_and_rejected_are_hidden_initially(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mapping = self.fixture(root, {"predictions": []})
            render_gallery(root, mapping)
            page = (root / "index.html").read_text()
            self.assertIn('id="showRetained" type="checkbox" checked', page)
            self.assertIn('id="showUncertain" type="checkbox">', page)
            self.assertIn('id="showRejected" type="checkbox">', page)
            self.assertIn('id="showLabels" type="checkbox">', page)

    def test_explicit_review_status_precedes_weak_reference_conflict(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mapping = self.fixture(
                root,
                {
                    "predictions": [
                        prediction(reviewStatus="retained", semanticConflict=True),
                        prediction(reviewStatus="uncertain", semanticConflict=False),
                        prediction("unknown", recognitionDecision="indeterminate"),
                    ]
                },
            )
            data = build_gallery_data(root, mapping)
            self.assertEqual(data["counts"], {"retained": 3, "uncertain": 2, "rejected": 0})
            self.assertTrue(data["frames"][0]["retained"][0]["semanticConflict"])

    def test_rejected_hypothesis_and_reason_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = prediction("speedboat")
            payload = {
                "predictions": [],
                "review": {
                    "rejected": [
                        {
                            "prediction": original,
                            "reason": "geometric_duplicate",
                            "representative": 0,
                        }
                    ],
                    "excludeRegions": [
                        {"id": "ownship", "polygon": [[0, 0.7], [0.4, 0.7], [0.5, 1], [0, 1]]}
                    ],
                    "counts": {"input": 1, "retained": 0, "rejected": 1},
                },
            }
            before = copy.deepcopy(payload)
            mapping = self.fixture(root, payload)
            data = build_gallery_data(root, mapping)
            self.assertEqual(data["counts"]["rejected"], 1)
            self.assertEqual(
                data["frames"][0]["rejected"][0]["prediction"]["bbox"], original["bbox"]
            )
            self.assertEqual(data["frames"][0]["rejected"][0]["reason"], "geometric_duplicate")
            self.assertEqual(data["frames"][0]["exclusions"][0]["id"], "ownship")
            self.assertEqual(payload, before)

    def test_unsafe_neighbor_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mapping = self.fixture(
                root,
                {
                    "predictions": [
                        prediction(
                            semanticEvidence={
                                "neighbors": [
                                    {
                                        "category": "buoy",
                                        "similarity": 0.8,
                                        "crop": "../../secrets.png",
                                    }
                                ]
                            }
                        )
                    ]
                },
            )
            with self.assertRaisesRegex(ValueError, "Unsafe gallery path"):
                build_gallery_data(root, mapping)

    def test_json_is_script_safe_even_with_untrusted_labels_and_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            attack = '</script><img src=x onerror=alert(1)>'
            mapping = self.fixture(root, {"predictions": [prediction(displayName=attack)]})
            mapping[0]["sourceImage"] = attack
            render_gallery(root, mapping, warnings=[attack])
            page = (root / "index.html").read_text()
            self.assertNotIn(attack, page)
            data = self.data_from_page(page)
            self.assertEqual(data["frames"][0]["sourceImage"], attack)
            self.assertEqual(data["frames"][0]["retained"][0]["displayName"], attack)
            self.assertIn('node.textContent=text', page)

    def test_editor_exports_normalized_campaign_config_without_truth(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mapping = self.fixture(root, {"predictions": []})
            render_gallery(root, mapping)
            page = (root / "index.html").read_text()
            self.assertIn("schema:'lotusim-rgb-search-regions-1'", page)
            self.assertIn("coordinateSystem:'normalized_image'", page)
            self.assertIn("excludeRegions:", page)
            self.assertIn("rgb-observer-regions.json", page)
            self.assertIn("matrix.inverse()", page)
            self.assertIn("ne modifie pas ce résultat", page)
            self.assertNotIn("target_name", page)

    def test_out_of_range_region_coordinates_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mapping = self.fixture(
                root,
                {
                    "predictions": [],
                    "review": {
                        "excludeRegions": [{"id": "ownship", "polygon": [[0, 0], [2, 0], [1, 1]]}]
                    },
                },
            )
            with self.assertRaisesRegex(ValueError, "normalized"):
                build_gallery_data(root, mapping)

    def test_only_observer_mask_namespace_is_allowed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mapping = self.fixture(
                root,
                {
                    "predictions": [],
                    "review": {"exclusionMask": "input/observer-exclusion/i000000.png"},
                },
            )
            data = build_gallery_data(root, mapping)
            self.assertEqual(
                data["frames"][0]["exclusionMask"], "input/observer-exclusion/i000000.png"
            )
            payload = {
                "predictions": [],
                "review": {"exclusionMask": "input/target-segmentation/i000000.png"},
            }
            (root / "predictions/i000000.json").write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "observer"):
                build_gallery_data(root, mapping)

    def test_gallery_accepts_backend_limit_of_128_vertices(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            polygon = [
                [
                    0.5 + 0.3 * math.cos(2 * math.pi * i / 128),
                    0.5 + 0.3 * math.sin(2 * math.pi * i / 128),
                ]
                for i in range(128)
            ]
            payload = {
                "predictions": [],
                "review": {"excludeRegions": [{"id": "ownship", "polygon": polygon}]},
            }
            mapping = self.fixture(root, payload)
            data = build_gallery_data(root, mapping)
            self.assertEqual(len(data["frames"][0]["exclusions"][0]["polygon"]), 128)
            payload["review"]["excludeRegions"][0]["polygon"].append([0.1, 0.1])
            (root / "predictions/i000000.json").write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "polygon"):
                build_gallery_data(root, mapping)

    def test_review_reasons_and_competing_classes_remain_visible_in_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            p = prediction(
                "speedboat",
                reviewStatus="uncertain",
                reviewReasons=["ambiguous_class_duplicates"],
                classAlternatives=[
                    {"category": "speedboat", "score": 0.61},
                    {"category": "ferry", "score": 0.60},
                ],
            )
            mapping = self.fixture(root, {"predictions": [p]})
            render_gallery(root, mapping)
            page = (root / "index.html").read_text()
            data = self.data_from_page(page)
            reviewed = data["frames"][0]["retained"][0]
            self.assertEqual(reviewed["category"], "speedboat")
            self.assertEqual(reviewed["reviewReasons"], ["ambiguous_class_duplicates"])
            self.assertEqual(
                [a["category"] for a in reviewed["classAlternatives"]], ["speedboat", "ferry"]
            )
            self.assertIn("Plusieurs classes concurrentes regroupées", page)
            self.assertIn("duplicate_tile_fragment", page)

    def test_invalid_frame_or_box_cannot_misplace_silently(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mapping = self.fixture(root, {"predictions": [prediction(bbox=[10, 20, -2, 30])]})
            with self.assertRaisesRegex(ValueError, "bounding box"):
                build_gallery_data(root, mapping)
            (root / "predictions/i000000.json").write_text('{"predictions":[]}')
            mapping[0]["width"] = 0
            with self.assertRaisesRegex(ValueError, "dimensions"):
                build_gallery_data(root, mapping)

    def test_missing_predictions_are_distinct_from_empty_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mapping = self.fixture(root)
            data = build_gallery_data(root, mapping)
            self.assertFalse(data["frames"][0]["predictionAvailable"])
            self.assertEqual(data["frames"][0]["retained"], [])

    def test_metrics_and_warnings_come_from_supplied_evaluator_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mapping = self.fixture(root, {"predictions": []})
            metrics = {
                "truePositives": 1,
                "falsePositives": 4,
                "falseNegatives": 7,
                "precision": 0.2,
                "recall": 0.125,
                "f1": 0.1538,
                "iouThreshold": 0.5,
            }
            render_gallery(root, mapping, metrics, ["Aucune annotation de référence"])
            data = self.data_from_page((root / "index.html").read_text())
            self.assertEqual(data["metrics"]["truePositives"], 1)
            self.assertEqual(data["warnings"], ["Aucune annotation de référence"])
            self.assertNotIn("frames", data["metrics"])

    def test_empty_diagnostic_page_is_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            render_gallery(root, [], warnings=["Worker failed"])
            data = self.data_from_page((root / "index.html").read_text())
            self.assertEqual(data["frames"], [])
            self.assertEqual(data["counts"], {"retained": 0, "uncertain": 0, "rejected": 0})


if __name__ == '__main__':
    unittest.main()
