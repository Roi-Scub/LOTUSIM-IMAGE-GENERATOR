using System;
using System.Linq;
using Lotusim.Dataset;
using UnityEditor;
using UnityEngine;

namespace Lotusim.EditorTools
{
    public static class DatasetRecognitionTests
    {
        [MenuItem("LOTUSim/Dataset/Validate visibility and NR PR R rules")]
        public static void Run()
        {
            Check(2, 1, 2, 2, "NR"); // 100% of two pixels is still not recognizable.
            Check(100, 10, 10, 100, "PR");
            Check(400, 20, 20, 400, "R");
            Check(400, 20, 20, 1000, "PR");
            Check(40, 8, 5, 1000, "NR");
            Check(400, 20, 20, 400, "NR", false, true); // Invisible contrast in RGB.
            Check(400, 20, 20, 400, "PR", true); // Potential frame truncation.
            Check(0, 0, 0, 400, "NR");
            Check(0, 0, 0, 0, "NR");
            var a = new DatasetFrameAnnotation
            {
                displayName = "voilier",
                visiblePercent = 38.4f,
                recognitionStatus = "PR",
                trackId = 123
            };
            Assert(DatasetRecognition.Label(a) == "voilier 38.4% PR", "Overlay uses visibility instead of track number");
            Assert(DatasetRecognition.Color("NR").r > DatasetRecognition.Color("NR").g, "NR red");
            Assert(DatasetRecognition.Color("R").g > DatasetRecognition.Color("R").r, "R green");
            DatasetAnnotationTests.Check();
            Debug.Log("[Recognition Tests] PASS two-pixel NR, R/PR/NR size and occlusion thresholds, clean-RGB contrast, truncation, hidden/no-box, percent label, colors and legacy coordinate tests.");
        }

        static void Check(int area, int boxWidth, int boxHeight, int fullArea, string expected, bool truncated = false, bool flat = false)
        {
            const int width = 64, height = 64;
            var rgb = Enumerable.Repeat(new Color32(40, 40, 40, 255), width * height).ToArray();
            var mask = new Color32[width * height];
            int[] box = area == 0 ? Array.Empty<int>() : new[]
            {
                20,
                20,
                boxWidth,
                boxHeight
            };
            int count = 0;
            for (int y = 20; y < 20 + boxHeight; y++)
                for (int x = 20; x < 20 + boxWidth; x++)
                    if (count++ < area)
                    {
                        int i = (height - 1 - y) * width + x;
                        mask[i] = new Color32(255, 255, 255, 255);
                        if (!flat)
                            rgb[i] = new Color32(230, 230, 230, 255);
                    }

            var a = new DatasetFrameAnnotation
            {
                visiblePixels = area,
                amodalPixelsInFrame = fullArea,
                bbox = box,
                geometricVisibleFractionInFrame = fullArea == 0 ? 0 : (float)area / fullArea,
                truncatedInFrame = truncated
            };
            DatasetRecognition.Assess(a, new DatasetMaskStats { area = fullArea, bbox = fullArea == 0 ? Array.Empty<int>() : new[] { 10, 10, 40, 40 } }, rgb, mask, width, height, new DatasetRecognitionSettings());
            Assert(a.recognitionStatus == expected, "Expected " + expected + " for " + area + " / " + fullArea + " pixels; got " + a.recognitionStatus);
            Assert(Math.Abs(a.visiblePercent - (fullArea == 0 ? 0 : 100f * area / fullArea)) < .001f, "Visible fraction percent");
            if (area == 0)
                Assert(a.bbox.Length == 0 && a.recognitionReason == (fullArea > 0 ? "fully_occluded" : "outside_frame_or_subpixel"), "No box for hidden or subpixel object");
        }

        static void Assert(bool okay, string message)
        {
            if (!okay)
                throw new InvalidOperationException("Recognition regression: " + message);
        }
    }
}
