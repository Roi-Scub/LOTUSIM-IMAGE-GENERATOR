"""Overlay readability/geometry tests, no inference or image output files."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from PIL import Image, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
from rgb_observer_worker import (_overlay_font, _overlay_text,
                                 overlay_label_layout, render_overlay)


def prediction(x=100, y=50, width=100, height=60, name="bouée", **extra):
    return {"bbox": [x, y, width, height], "category": "buoy", "displayName": name,
            "score": .45, "semanticConflict": False, **extra}


class OverlayTests(unittest.TestCase):
    def test_output_dimensions_and_inputs_unchanged(self):
        image = Image.new("RGB", (400, 240), "#abcdef")
        pixels = image.tobytes()
        predictions = [prediction()]
        original = copy.deepcopy(predictions)
        result = render_overlay(image, predictions)
        self.assertEqual(result.size, image.size)
        self.assertEqual(result.mode, "RGB")
        self.assertEqual(image.tobytes(), pixels)
        self.assertEqual(predictions, original)
        self.assertNotEqual(result.tobytes(), pixels)

    def test_unicode_text_preserved_with_real_font(self):
        text = _overlay_text(prediction(semanticConflict=True), True)
        self.assertIn("bouée", text)
        self.assertIn("score brut 45%", text)
        self.assertIn("réf.", text)
        self.assertNotIn("probabilité", text)
        self.assertNotIn("sûreté", text)
        font, unicode_supported = _overlay_font(16)
        if unicode_supported:
            self.assertIsNotNone(font.getmask("bouée · hélicoptère · réf."))

    def test_only_default_font_fallback_transliterates(self):
        text = _overlay_text(prediction(name="hélicoptère", semanticConflict=True), False)
        self.assertTrue(text.isascii())
        self.assertIn("helicoptere", text)
        fallback = ImageFont.load_default()
        with patch("rgb_observer_worker._overlay_font", return_value=(fallback, False)):
            layout = overlay_label_layout((400, 200), [prediction()])
            self.assertTrue(layout[0]["text"].isascii())

    def test_right_bottom_and_long_labels_stay_inside_native_image(self):
        predictions = [prediction(x=125, y=62, width=20, height=15,
                                  name="un nom volontairement beaucoup trop long pour cette image")]
        layout = overlay_label_layout((150, 80), predictions)
        left, top, right, bottom = layout[0]["labelRect"]
        self.assertTrue(0 <= left < right <= 150)
        self.assertTrue(0 <= top < bottom <= 80)
        self.assertLessEqual(layout[0]["font"].getbbox(layout[0]["text"])[2], 150)

    def test_multiple_labels_greedily_avoid_overlap_when_possible(self):
        predictions = [prediction(x=100, y=70) for _ in range(4)]
        layout = overlay_label_layout((600, 300), predictions)
        for index, first in enumerate(layout):
            for second in layout[index+1:]:
                a, b = first["labelRect"], second["labelRect"]
                overlap = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(
                    0, min(a[3], b[3])-max(a[1], b[1]))
                self.assertEqual(overlap, 0)

    def test_small_images_keep_all_predictions_and_do_not_overflow(self):
        for width, height in [(64, 32), (20, 10), (1, 1)]:
            predictions = [prediction(x=width-1, y=height-1, width=1, height=1)]*3
            layout = overlay_label_layout((width, height), predictions)
            self.assertEqual(len(layout), len(predictions))
            for item in layout:
                left, top, right, bottom = item["labelRect"]
                self.assertTrue(0 <= left < right <= width)
                self.assertTrue(0 <= top < bottom <= height)
            self.assertEqual(render_overlay(Image.new("RGB", (width, height)), predictions).size,
                             (width, height))

    def test_empty_predictions_and_nonrgb_input(self):
        image = Image.new("RGBA", (40, 40), "red")
        self.assertEqual(render_overlay(image, []).mode, "RGB")
        self.assertEqual(overlay_label_layout(image.size, []), [])

    def test_score_label_never_uses_calibrated_precision_as_raw_score(self):
        value = prediction(calibratedConfidencePercent=99, confidenceCalibrated=True)
        text = _overlay_text(value)
        self.assertIn("45%", text)
        self.assertNotIn("99", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
