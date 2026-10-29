using System;
using System.Linq;
using System.Globalization;
using Lotusim.Dataset;
using UnityEditor;
using UnityEngine;

namespace Lotusim.EditorTools
{
    public static class DatasetAnnotationTests
    {
        [MenuItem("LOTUSim/Dataset/Validate annotation coordinates and RLE")]
        public static void Run()
        {
            Check();
            Debug.Log("[Dataset] Annotation coordinate/RLE/label tests PASS.");
        }

        public static void Check()
        {
            var mask = new Color32[12];
            var empty = DatasetAnnotationExport.Measure(mask, 4, 3);
            Assert(empty.area == 0 && empty.bbox.Length == 0, "Empty mask has no box");
            Assert(DatasetAnnotationExport.Rle(mask, 4, 3).SequenceEqual(new[] { 12 }), "Empty COCO RLE");
            mask[2 * 4 + 1] = new Color32(255, 255, 255, 255);
            mask[1 * 4 + 1] = new Color32(255, 255, 255, 255);
            var stats = DatasetAnnotationExport.Measure(mask, 4, 3);
            Assert(stats.area == 2 && stats.bbox.SequenceEqual(new[] { 1, 0, 1, 2 }), "Bottom-left readback to top-left box");
            Assert(stats.touchesImageEdge, "Image-edge truncation flag");
            var rle = DatasetAnnotationExport.Rle(mask, 4, 3);
            Assert(rle.SequenceEqual(new[] { 3, 2, 7 }) && rle.Sum() == 12, "Column-major COCO RLE");
            var yolo = DatasetAnnotationExport.Yolo(stats.bbox, 4, 3).Trim().Split(' ');
            Assert(yolo[0] == "0" && Math.Abs(float.Parse(yolo[1], CultureInfo.InvariantCulture) - .375f) < 1e-6f && Math.Abs(float.Parse(yolo[2], CultureInfo.InvariantCulture) - 1f / 3) < 1e-6f && Math.Abs(float.Parse(yolo[3], CultureInfo.InvariantCulture) - .25f) < 1e-6f, "YOLO normalization/class index");
            mask = Enumerable.Repeat(new Color32(255, 255, 255, 255), 12).ToArray();
            Assert(DatasetAnnotationExport.Rle(mask, 4, 3).SequenceEqual(new[] { 0, 12 }), "Foreground-first RLE starts with zero background run");
            Assert(DatasetAnnotationExport.Measure(mask, 4, 3).bbox.SequenceEqual(new[] { 0, 0, 4, 3 }), "Full-frame inclusive box");
            CheckLabels();
        }

        static void CheckLabels()
        {
            Assert(DatasetOverlayLabel.DisplayName("buoy") == "bouée", "French buoy label, stable machine category");
            Assert(DatasetOverlayLabel.DisplayName("airplane") == "avion", "French aircraft label");
            Assert(DatasetOverlayLabel.DisplayName("buoy", "  cible  ") == "cible", "Optional label override");
            const int width = 160, height = 100;
            var original = Enumerable.Repeat(new Color32(80, 90, 100, 255), width * height).ToArray();
            var pixels = original.ToArray();
            var stats = new DatasetMaskStats
            {
                area = 400,
                bbox = new[]
                {
                    60,
                    50,
                    20,
                    20
                }
            };
            var rect = DatasetOverlayLabel.Paint(pixels, width, height, stats, "bouée");
            Assert(rect.SequenceEqual(new[] { 60, 34, 33, 14 }), "Class label above box with top-left origin");
            Assert(stats.bbox.SequenceEqual(new[] { 60, 50, 20, 20 }), "Text does not alter object box");
            Assert(pixels.Any(c => c.r == 255 && c.g == 255 && c.b == 255), "Readable text pixels");
            for (int y = 0; y < height; y++)
                for (int x = 0; x < width; x++)
                {
                    int i = (height - 1 - y) * width + x;
                    if (x < rect[0] || x >= rect[0] + rect[2] || y < rect[1] || y >= rect[1] + rect[3])
                        Assert(pixels[i].Equals(original[i]), "Text remains inside its plate");
                }

            var unaccented = original.ToArray();
            DatasetOverlayLabel.Paint(unaccented, width, height, stats, "bouee");
            Assert(!pixels.SequenceEqual(unaccented), "Accented e has visible accent pixels");
            var decomposed = original.ToArray();
            DatasetOverlayLabel.Paint(decomposed, width, height, stats, "boue\u0301e");
            Assert(pixels.SequenceEqual(decomposed), "Composed/decomposed French label equality");
            stats.bbox = new[]
            {
                159,
                0,
                1,
                1
            };
            rect = DatasetOverlayLabel.Paint(pixels, width, height, stats, "bouée");
            Assert(rect[0] >= 0 && rect[1] >= 0 && rect[0] + rect[2] <= width && rect[1] + rect[3] <= height, "Label clipped to image near top-right edge");
            pixels = original.ToArray();
            rect = DatasetOverlayLabel.Paint(pixels, width, height, new DatasetMaskStats(), "bouée");
            Assert(rect.Length == 0 && pixels.SequenceEqual(original), "Fully hidden object receives no visible text");
            pixels = new Color32[16 * 16];
            rect = DatasetOverlayLabel.Paint(pixels, 16, 16, new DatasetMaskStats { area = 1, bbox = new[] { 0, 15, 1, 1 } }, "hélicoptère très long");
            Assert(rect[0] + rect[2] <= 16 && rect[1] + rect[3] <= 16, "Small-image/long-label bounds");
            var plates = new System.Collections.Generic.List<int[]>();
            pixels = original.ToArray();
            stats = new DatasetMaskStats
            {
                area = 400,
                bbox = new[]
                {
                    60,
                    50,
                    20,
                    20
                }
            };
            for (int i = 0; i < 4; i++)
            {
                rect = DatasetOverlayLabel.Paint(pixels, width, height, stats, "avion " + i, plates);
                Assert(!plates.Any(p => rect[0] < p[0] + p[2] && rect[0] + rect[2] > p[0] && rect[1] < p[1] + p[3] && rect[1] + rect[3] > p[1]), "Multiple labels do not overlap");
                plates.Add(rect);
            }
        }

        static void Assert(bool ok, string label)
        {
            if (!ok)
                throw new InvalidOperationException("Annotation test failed: " + label);
        }
    }
}
