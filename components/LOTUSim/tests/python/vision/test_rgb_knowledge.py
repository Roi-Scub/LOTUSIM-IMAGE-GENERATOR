#!/usr/bin/env python3
"""Knowledge provenance and RGB-only boundary tests, without model loading."""

import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image, PngImagePlugin

from lotusim_image_generator.vision.knowledge import (
    KnowledgeIndex,
    VisualEncoder,
    build_knowledge,
    pixel_sha256,
)


class FakeEncoder:
    description = "test_rgb_mean_l2"

    def encode(self, image):
        colors = list(image.convert("RGB").getdata())
        return [sum(pixel[channel] for pixel in colors) + 1 for channel in range(3)]


class FingerprintedFakeEncoder(FakeEncoder):
    def __init__(self, weights_sha256):
        self.weights_sha256 = weights_sha256


class KnowledgeTests(unittest.TestCase):
    def campaign(self, root, name, color=(220, 40, 20), annotation=True, bbox=None):
        campaign = root / name
        (campaign / "rgb").mkdir(parents=True)
        (campaign / "annotations").mkdir()
        image = Image.new("RGB", (32, 24), color)
        image.save(campaign / "rgb/f000000.png")
        if annotation:
            (campaign / "annotations/f000000.json").write_text(
                json.dumps(
                    {
                        "width": 32,
                        "height": 24,
                        "activeObjects": [
                            {"instance": "SECRET_INSTANCE", "modelName": "SECRET_ASSET"}
                        ],
                        "annotations": [
                            {
                                "category": "buoy",
                                "instance": "SECRET_INSTANCE",
                                "visiblePixels": 400,
                                "bbox": bbox or [0, 0, 24, 20],
                            }
                        ],
                    }
                )
            )
        return campaign

    def test_pixel_duplicates_ignore_png_metadata_and_preserve_groups(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            a, b = self.campaign(root, "source_a"), self.campaign(root, "source_b")
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text("comment", "Different metadata")
            with Image.open(b / "rgb/f000000.png") as reopened:
                pixels = reopened.copy()
            pixels.save(b / "rgb/f000000.png", pnginfo=metadata)
            manifest = build_knowledge(
                [{"path": a, "group": "campaign-a"}, {"path": b, "group": "campaign-b"}],
                root / "knowledge",
                FakeEncoder(),
                ["buoy"],
            )
            self.assertEqual(manifest["exampleCount"], 1)
            self.assertEqual(manifest["duplicateCount"], 1)
            provenance = json.loads((root / "knowledge/coordinator/provenance.json").read_text())
            self.assertEqual(
                {f["group"] for f in provenance["frames"]}, {"campaign-a", "campaign-b"}
            )
            self.assertEqual(
                provenance["frames"][0]["rgbPixelSha256"], provenance["frames"][1]["rgbPixelSha256"]
            )

    def test_worker_public_does_not_contain_source_names_poses_or_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.campaign(root, "SECRET_CAMPAIGN")
            build_knowledge([source], root / "knowledge", FakeEncoder(), ["buoy"])
            text = (root / "knowledge/public/index.json").read_text()
            for forbidden in ["SECRET", "bbox", "rgbPixelSha256", "annotationPath", str(source)]:
                self.assertNotIn(forbidden, text)
            self.assertFalse((root / "knowledge/public/annotations").exists())
            self.assertFalse((root / "knowledge/public/overlays").exists())
            provenance = json.loads((root / "knowledge/coordinator/provenance.json").read_text())
            self.assertEqual(provenance["examples"][0]["assetGroup"], "SECRET_ASSET")

    def test_no_overlay_pixels_and_overlay_source_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.campaign(root, "source")
            (source / "overlays").mkdir()
            Image.new("RGB", (32, 24), "blue").save(source / "overlays/f000000.png")
            build_knowledge([source], root / "knowledge", FakeEncoder(), ["buoy"])
            with Image.open(root / "knowledge/public/crops/e000000.png") as crop:
                self.assertEqual(crop.getpixel((0, 0)), (220, 40, 20))
            with self.assertRaises(ValueError):
                build_knowledge([source / "overlays"], root / "bad", FakeEncoder(), ["buoy"])

    def test_bounds_clipped_and_invalid_box_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.campaign(root, "source", bbox=[-8, -6, 50, 50])
            build_knowledge([source], root / "knowledge", FakeEncoder(), ["buoy"])
            with Image.open(root / "knowledge/public/crops/e000000.png") as crop:
                self.assertEqual(crop.size, (32, 24))
            other = self.campaign(root, "bad", bbox=[0, 0, -4, 8])
            result = build_knowledge([other], root / "rejected", FakeEncoder(), ["buoy"])
            self.assertEqual(result["exampleCount"], 0)
            self.assertEqual(result["rejectedCount"], 1)

    def test_unannotated_indexed_without_invented_class(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.campaign(root, "raw", annotation=False)
            result = build_knowledge([source], root / "knowledge", FakeEncoder(), ["buoy"])
            self.assertEqual(result["unlabeledFrameCount"], 1)
            self.assertEqual(result["exampleCount"], 0)
            index = KnowledgeIndex.load(root / "knowledge")
            query = index.query(Image.new("RGB", (12, 12), "red"), FakeEncoder())
            self.assertEqual(query["topCategory"], "unknown")
            self.assertIsNone(query["similarity"])
            self.assertFalse(query["probabilityCalibrated"])

    def test_query_is_similarity_suggestion_not_probability(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.campaign(root, "source")
            build_knowledge([source], root / "knowledge", FakeEncoder(), ["buoy"])
            index = KnowledgeIndex.load(root / "knowledge/public")
            query = index.query(Image.new("RGB", (8, 8), (220, 40, 20)), FakeEncoder())
            self.assertEqual(query["topCategory"], "buoy")
            self.assertGreater(query["similarity"], 0.99)
            self.assertIsNone(query["margin"])
            self.assertTrue(query["classificationIsSuggestion"])
            self.assertEqual(query["scoreMeaning"], "cosine_similarity_not_probability")

    def test_coco_only_source_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.campaign(root, "source", annotation=False)
            (source / "annotations.coco.json").write_text(
                json.dumps(
                    {
                        "images": [{"id": 1, "file_name": "rgb/f000000.png"}],
                        "categories": [{"id": 1, "name": "buoy"}],
                        "annotations": [
                            {"image_id": 1, "category_id": 1, "bbox": [0, 0, 20, 20], "area": 400}
                        ],
                    }
                )
            )
            result = build_knowledge([source], root / "knowledge", FakeEncoder(), ["buoy"])
            self.assertEqual(result["classCounts"], {"buoy": 1})

    def test_class_limits_and_empty_subpixel_references(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self.campaign(root, "first", color=(240, 50, 20))
            second = self.campaign(root, "second", color=(180, 70, 20))
            third = self.campaign(root, "third", color=(100, 40, 20))
            result = build_knowledge(
                [first, second, third], root / "knowledge", FakeEncoder(), ["buoy"], max_per_class=2
            )
            self.assertEqual(result["exampleCount"], 2)
            tiny = self.campaign(root, "tiny", bbox=[0, 0, 1, 1])
            metadata = tiny / "annotations/f000000.json"
            payload = json.loads(metadata.read_text())
            payload["annotations"][0]["visiblePixels"] = 1
            metadata.write_text(json.dumps(payload))
            result = build_knowledge([tiny], root / "subpixel", FakeEncoder(), ["buoy"])
            self.assertEqual(result["exampleCount"], 0)

    def test_query_margin_is_against_other_category_not_second_same_class(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            a = self.campaign(root, "red", color=(240, 20, 20))
            b = self.campaign(root, "blue", color=(20, 20, 240))
            reference = b / "annotations/f000000.json"
            payload = json.loads(reference.read_text())
            payload["annotations"][0]["category"] = "drone"
            reference.write_text(json.dumps(payload))
            build_knowledge([a, b], root / "knowledge", FakeEncoder(), ["buoy", "drone"])
            query = KnowledgeIndex.load(root / "knowledge").query(
                Image.new("RGB", (8, 8), (240, 20, 20)), FakeEncoder(), k=1
            )
            self.assertEqual(query["topCategory"], "buoy")
            self.assertEqual(len(query["neighbors"]), 1)
            self.assertGreater(query["margin"], 0.5)
            self.assertEqual(query["distinctCategoryCount"], 2)

    def test_weight_fingerprint_roundtrip_and_mismatched_queries_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.campaign(root, "source")
            fingerprint = "a" * 64
            encoder = FingerprintedFakeEncoder(fingerprint)
            manifest = build_knowledge([source], root / "knowledge", encoder, ["buoy"])
            self.assertEqual(manifest["weightsSha256"], fingerprint)
            public = json.loads((root / "knowledge/public/index.json").read_text())
            self.assertEqual(public["weightsSha256"], fingerprint)
            index = KnowledgeIndex.load(root / "knowledge")
            self.assertEqual(index.weights_sha256, fingerprint)
            self.assertFalse(index.legacy_weights_unverified)
            image = Image.new("RGB", (12, 12), "red")
            result = index.query(image, encoder)
            self.assertTrue(result["knowledgeWeightsVerified"])
            self.assertEqual(result["knowledgeWeightFingerprintStatus"], "verified")
            for other in (FingerprintedFakeEncoder("b" * 64), FakeEncoder()):
                with self.assertRaisesRegex(ValueError, "weights fingerprints"):
                    index.query(image, other)

    def test_legacy_knowledge_is_supported_but_not_claimed_weight_verified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.campaign(root, "source")
            manifest = build_knowledge([source], root / "knowledge", FakeEncoder(), ["buoy"])
            self.assertNotIn("weightsSha256", manifest)
            index = KnowledgeIndex.load(root / "knowledge")
            self.assertTrue(index.legacy_weights_unverified)
            result = index.query(
                Image.new("RGB", (12, 12), "red"), FingerprintedFakeEncoder("a" * 64)
            )
            self.assertFalse(result["knowledgeWeightsVerified"])
            self.assertEqual(result["knowledgeWeightFingerprintStatus"], "legacy_unverified")

    def test_encoder_optional_fingerprint_is_validated_without_loading_model(self):
        self.assertEqual(
            VisualEncoder(None, None, weights_sha256="a" * 64).weights_sha256, "a" * 64
        )
        self.assertIsNone(VisualEncoder(None, None).weights_sha256)
        for invalid in ("main", "A" * 64, "a" * 63, 123):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                VisualEncoder(None, None, weights_sha256=invalid)


if __name__ == "__main__":
    unittest.main()
