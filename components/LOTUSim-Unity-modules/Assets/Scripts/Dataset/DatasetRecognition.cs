using System;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;

namespace Lotusim.Dataset
{
    [Serializable]
    public sealed class DatasetRecognitionSettings
    {
        public string version = "rgb-recognizability-heuristic-1";
        public int partialMinPixels = 32, recognizableMinPixels = 256, partialMinBoxSide = 4, recognizableMinBoxSide = 12;
        public float partialMinVisibleFraction = .1f, recognizableMinVisibleFraction = .65f;
        public float partialMinContrast = .025f, recognizableMinContrast = .08f;
        public void Validate()
        {
            if (partialMinPixels < 3 || recognizableMinPixels < partialMinPixels || partialMinBoxSide < 2 || recognizableMinBoxSide < partialMinBoxSide || !Range(partialMinVisibleFraction, 0, 1) || !Range(recognizableMinVisibleFraction, partialMinVisibleFraction, 1) || !Range(partialMinContrast, 0, 1) || !Range(recognizableMinContrast, partialMinContrast, 1))
                throw new ArgumentException("Invalid NR / PR / R heuristic thresholds.");
        }

        static bool Range(float x, float a, float b) => !float.IsNaN(x) && !float.IsInfinity(x) && x >= a && x <= b;
    }

    public static class DatasetRecognition
    {
        public static Color32 Color(string status) => status == "R" ? new Color32(40, 230, 100, 255) : status == "PR" ? new Color32(255, 196, 32, 255) : new Color32(240, 65, 65, 255);
        public static string Label(DatasetFrameAnnotation a) => a.displayName + " " + a.visiblePercent.ToString("0.0", CultureInfo.InvariantCulture) + "% " + a.recognitionStatus;
        public static void Assess(DatasetFrameAnnotation a, DatasetMaskStats full, Color32[] rgb, Color32[] mask, int width, int height, DatasetRecognitionSettings settings)
        {
            settings = settings ?? new DatasetRecognitionSettings();
            settings.Validate();
            a.amodalBBoxInFrame = full.bbox;
            a.visiblePercent = 100 * a.geometricVisibleFractionInFrame;
            a.occludedPercent = full.area > 0 ? 100 - a.visiblePercent : 0;
            a.recognitionRuleVersion = settings.version;
            a.recognitionStatus = "NR";
            a.recognitionMeaning = "heuristic_native_pixels_visibility_and_rgb_contrast_not_validated_human_recognition";
            a.recognitionModality = "rgb";
            a.rgbLocalContrast = Contrast(rgb, mask, a.bbox, width, height, out int samples);
            a.contrastBackgroundPixels = samples;
            var reasons = new List<string>();
            int side = a.bbox.Length == 4 ? Math.Min(a.bbox[2], a.bbox[3]) : 0;
            if (a.visiblePixels == 0)
            {
                a.recognitionReason = full.area > 0 ? "fully_occluded" : "outside_frame_or_subpixel";
                a.needsManualReview = true;
                return;
            }

            bool partial = a.visiblePixels >= settings.partialMinPixels && side >= settings.partialMinBoxSide && a.geometricVisibleFractionInFrame >= settings.partialMinVisibleFraction && samples > 0 && a.rgbLocalContrast >= settings.partialMinContrast;
            bool recognizable = partial && a.visiblePixels >= settings.recognizableMinPixels && side >= settings.recognizableMinBoxSide && a.geometricVisibleFractionInFrame >= settings.recognizableMinVisibleFraction && a.rgbLocalContrast >= settings.recognizableMinContrast && !a.truncatedInFrame;
            a.recognitionStatus = recognizable ? "R" : partial ? "PR" : "NR";
            if (a.visiblePixels < (partial ? settings.recognizableMinPixels : settings.partialMinPixels))
                reasons.Add("small_visible_area");
            if (side < (partial ? settings.recognizableMinBoxSide : settings.partialMinBoxSide))
                reasons.Add("small_visible_box_side");
            if (a.geometricVisibleFractionInFrame < (partial ? settings.recognizableMinVisibleFraction : settings.partialMinVisibleFraction))
                reasons.Add("occlusion");
            if (samples == 0)
                reasons.Add("no_background_contrast_sample");
            else if (a.rgbLocalContrast < (partial ? settings.recognizableMinContrast : settings.partialMinContrast))
                reasons.Add("low_rgb_contrast");
            if (a.truncatedInFrame)
                reasons.Add("image_edge_truncation");
            a.recognitionReason = string.Join(";", reasons);
            a.needsManualReview |= !recognizable;
            if (a.needsManualReview && a.recognitionReason.Length > 0)
                a.reviewReason = a.recognitionReason;
        }

        // RMS luma difference against the immediate background ring, measured
        // on the CLEAN RGB at native resolution. This is a documented proxy,
        // not a semantic classifier, confidence score or full-object visibility.
        public static float Contrast(Color32[] rgb, Color32[] mask, int[] box, int width, int height, out int backgroundPixels)
        {
            backgroundPixels = 0;
            if (box.Length != 4)
                return 0;
            if (rgb.Length != width * height || mask.Length != rgb.Length)
                throw new ArgumentException("RGB/mask contrast dimensions differ.");
            int pad = Math.Max(3, Math.Min(16, Math.Min(box[2], box[3]) / 4));
            double sum = 0;
            int l = Math.Max(0, box[0] - pad), r = Math.Min(width, box[0] + box[2] + pad), t = Math.Max(0, box[1] - pad), b = Math.Min(height, box[1] + box[3] + pad);
            for (int y = t; y < b; y++)
                for (int x = l; x < r; x++)
                    if (x < box[0] || x >= box[0] + box[2] || y < box[1] || y >= box[1] + box[3])
                    {
                        int i = (height - 1 - y) * width + x;
                        if (mask[i].r < 128)
                        {
                            sum += Luma(rgb[i]);
                            backgroundPixels++;
                        }
                    }

            if (backgroundPixels == 0)
                return 0;
            double mean = sum / backgroundPixels, squared = 0;
            int count = 0;
            for (int y = box[1]; y < box[1] + box[3]; y++)
                for (int x = box[0]; x < box[0] + box[2]; x++)
                {
                    int i = (height - 1 - y) * width + x;
                    if (mask[i].r >= 128)
                    {
                        double difference = Luma(rgb[i]) - mean;
                        squared += difference * difference;
                        count++;
                    }
                }

            return count == 0 ? 0 : (float)Math.Sqrt(squared / count);
        }

        static double Luma(Color32 c) => (.2126 * c.r + .7152 * c.g + .0722 * c.b) / 255;
    }
}
