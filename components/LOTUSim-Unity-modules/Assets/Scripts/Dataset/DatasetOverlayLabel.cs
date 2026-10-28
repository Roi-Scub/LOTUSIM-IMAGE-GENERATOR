using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;

namespace Lotusim.Dataset
{
    // CPU-only text on the diagnostic PNG, never on RGB or an instance mask.
    // A small embedded font avoids another camera, UI, native texture or font
    // allocation during capture, and keeps accented French class names usable.
    public static class DatasetOverlayLabel
    {
        const int GlyphWidth = 5, GlyphHeight = 10, Advance = 6;
        static readonly Dictionary<char, string> Glyphs = new Dictionary<char, string>
        {
            ['A'] = "01110/10001/10001/11111/10001/10001/10001",
            ['B'] = "11110/10001/10001/11110/10001/10001/11110",
            ['C'] = "01111/10000/10000/10000/10000/10000/01111",
            ['D'] = "11110/10001/10001/10001/10001/10001/11110",
            ['E'] = "11111/10000/10000/11110/10000/10000/11111",
            ['F'] = "11111/10000/10000/11110/10000/10000/10000",
            ['G'] = "01111/10000/10000/10111/10001/10001/01111",
            ['H'] = "10001/10001/10001/11111/10001/10001/10001",
            ['I'] = "01110/00100/00100/00100/00100/00100/01110",
            ['J'] = "00111/00010/00010/00010/00010/10010/01100",
            ['K'] = "10001/10010/10100/11000/10100/10010/10001",
            ['L'] = "10000/10000/10000/10000/10000/10000/11111",
            ['M'] = "10001/11011/10101/10101/10001/10001/10001",
            ['N'] = "10001/11001/10101/10011/10001/10001/10001",
            ['O'] = "01110/10001/10001/10001/10001/10001/01110",
            ['P'] = "11110/10001/10001/11110/10000/10000/10000",
            ['Q'] = "01110/10001/10001/10001/10101/10010/01101",
            ['R'] = "11110/10001/10001/11110/10100/10010/10001",
            ['S'] = "01111/10000/10000/01110/00001/00001/11110",
            ['T'] = "11111/00100/00100/00100/00100/00100/00100",
            ['U'] = "10001/10001/10001/10001/10001/10001/01110",
            ['V'] = "10001/10001/10001/10001/10001/01010/00100",
            ['W'] = "10001/10001/10001/10101/10101/10101/01010",
            ['X'] = "10001/10001/01010/00100/01010/10001/10001",
            ['Y'] = "10001/10001/01010/00100/00100/00100/00100",
            ['Z'] = "11111/00001/00010/00100/01000/10000/11111",
            ['a'] = "00000/00000/01110/00001/01111/10001/01111",
            ['b'] = "10000/10000/10110/11001/10001/10001/11110",
            ['c'] = "00000/00000/01111/10000/10000/10000/01111",
            ['d'] = "00001/00001/01101/10011/10001/10001/01111",
            ['e'] = "00000/00000/01110/10001/11111/10000/01110",
            ['f'] = "00110/01001/01000/11100/01000/01000/01000",
            ['g'] = "00000/01111/10001/10001/01111/00001/01110",
            ['h'] = "10000/10000/10110/11001/10001/10001/10001",
            ['i'] = "00100/00000/01100/00100/00100/00100/01110",
            ['j'] = "00010/00000/00110/00010/00010/10010/01100",
            ['k'] = "10000/10000/10010/10100/11000/10100/10010",
            ['l'] = "01100/00100/00100/00100/00100/00100/01110",
            ['m'] = "00000/00000/11010/10101/10101/10101/10101",
            ['n'] = "00000/00000/10110/11001/10001/10001/10001",
            ['o'] = "00000/00000/01110/10001/10001/10001/01110",
            ['p'] = "00000/11110/10001/10001/11110/10000/10000",
            ['q'] = "00000/01111/10001/10001/01111/00001/00001",
            ['r'] = "00000/00000/10110/11001/10000/10000/10000",
            ['s'] = "00000/00000/01111/10000/01110/00001/11110",
            ['t'] = "01000/01000/11100/01000/01000/01001/00110",
            ['u'] = "00000/00000/10001/10001/10001/10011/01101",
            ['v'] = "00000/00000/10001/10001/10001/01010/00100",
            ['w'] = "00000/00000/10001/10001/10101/10101/01010",
            ['x'] = "00000/00000/10001/01010/00100/01010/10001",
            ['y'] = "00000/10001/10001/10001/01111/00001/01110",
            ['z'] = "00000/00000/11111/00010/00100/01000/11111",
            ['0'] = "01110/10001/10011/10101/11001/10001/01110",
            ['1'] = "00100/01100/00100/00100/00100/00100/01110",
            ['2'] = "01110/10001/00001/00010/00100/01000/11111",
            ['3'] = "11110/00001/00001/01110/00001/00001/11110",
            ['4'] = "00010/00110/01010/10010/11111/00010/00010",
            ['5'] = "11111/10000/10000/11110/00001/00001/11110",
            ['6'] = "01110/10000/10000/11110/10001/10001/01110",
            ['7'] = "11111/00001/00010/00100/01000/01000/01000",
            ['8'] = "01110/10001/10001/01110/10001/10001/01110",
            ['9'] = "01110/10001/10001/01111/00001/00001/01110",
            [' '] = "00000/00000/00000/00000/00000/00000/00000",
            ['-'] = "00000/00000/00000/11111/00000/00000/00000",
            ['_'] = "00000/00000/00000/00000/00000/00000/11111",
            ['.'] = "00000/00000/00000/00000/00000/00110/00110",
            ['?'] = "01110/10001/00001/00010/00100/00000/00100",
            ['%'] = "11001/11010/00100/01000/10110/00110/00000"
        };
        public static string DisplayName(string category, string requested = null)
        {
            if (!string.IsNullOrWhiteSpace(requested))
                return requested.Trim();
            switch (category)
            {
                case "buoy":
                    return "bouée";
                case "airplane":
                    return "avion";
                case "helicopter":
                    return "hélicoptère";
                case "small_drone":
                    return "drone";
                case "drone":
                    return "drone";
                case "bird":
                    return "oiseau";
                case "seagull":
                    return "mouette";
                default:
                    return category;
            }
        }

        // Return label plate bounds with the same top-left origin as COCO.
        public static int[] Paint(Color32[] pixels, int width, int height, DatasetMaskStats stats, string label) => Paint(pixels, width, height, stats, label, null);
        public static int[] Paint(Color32[] pixels, int width, int height, DatasetMaskStats stats, string label, List<int[]> occupied) => Paint(pixels, width, height, stats, label, occupied, new Color32(0, 255, 120, 255));
        public static int[] Paint(Color32[] pixels, int width, int height, DatasetMaskStats stats, string label, List<int[]> occupied, Color32 border)
        {
            if (pixels == null || width <= 0 || height <= 0 || pixels.Length != checked(width * height))
                throw new ArgumentException("Invalid overlay dimensions.");
            if (stats.area == 0 || string.IsNullOrWhiteSpace(label))
                return Array.Empty<int>();
            int scale = Math.Max(1, Math.Min(3, height / 360)), padding = 2 * scale, gap = 2 * scale;
            string text = label.Normalize(NormalizationForm.FormC);
            int fit = Math.Max(1, (width - 2 * padding + scale) / (Advance * scale));
            if (text.Length > fit)
                text = fit > 3 ? text.Substring(0, fit - 3) + "..." : text.Substring(0, fit);
            int plateWidth = Math.Min(width, (text.Length * Advance - 1) * scale + 2 * padding);
            int plateHeight = Math.Min(height, GlyphHeight * scale + 2 * padding);
            int left = Math.Max(0, Math.Min(stats.bbox[0], width - plateWidth));
            int top = stats.bbox[1] - gap - plateHeight;
            if (top < 0)
            {
                int below = stats.bbox[1] + stats.bbox[3] + gap;
                top = below + plateHeight <= height ? below : Math.Max(0, Math.Min(stats.bbox[1] + gap, height - plateHeight));
            }

            int nominalLeft = left, nominalTop = top;
            if (occupied != null && occupied.Exists(rect => Overlap(left, top, plateWidth, plateHeight, rect, gap)))
            {
                bool found = false;
                for (int y = top - plateHeight - gap; y >= 0; y -= plateHeight + gap)
                    if (!occupied.Exists(rect => Overlap(left, y, plateWidth, plateHeight, rect, gap)))
                    {
                        top = y;
                        found = true;
                        break;
                    }

                if (!found)
                    for (int y = stats.bbox[1] + stats.bbox[3] + gap; y + plateHeight <= height; y += plateHeight + gap)
                        if (!occupied.Exists(rect => Overlap(left, y, plateWidth, plateHeight, rect, gap)))
                        {
                            top = y;
                            found = true;
                            break;
                        }

                if (!found)
                    for (int y = 0; y + plateHeight <= height && !found; y += plateHeight + gap)
                        for (int x = 0; x + plateWidth <= width; x += plateWidth + gap)
                            if (!occupied.Exists(rect => Overlap(x, y, plateWidth, plateHeight, rect, gap)))
                            {
                                left = x;
                                top = y;
                                found = true;
                                break;
                            }
            }

            var white = new Color32(255, 255, 255, 255);
            if (left != nominalLeft || top != nominalTop)
            {
                int x0 = left + plateWidth / 2, y0 = top + plateHeight / 2, x1 = stats.bbox[0] + stats.bbox[2] / 2, y1 = stats.bbox[1];
                int steps = Math.Max(Math.Abs(x1 - x0), Math.Abs(y1 - y0));
                for (int s = 0; s <= steps; s++)
                {
                    int x = steps == 0 ? x0 : x0 + (x1 - x0) * s / steps, y = steps == 0 ? y0 : y0 + (y1 - y0) * s / steps;
                    if (x >= 0 && x < width && y >= 0 && y < height && !occupied.Exists(r => x >= r[0] && x < r[0] + r[2] && y >= r[1] && y < r[1] + r[3]))
                        pixels[(height - 1 - y) * width + x] = border;
                }
            }

            for (int y = top; y < top + plateHeight; y++)
                for (int x = left; x < left + plateWidth; x++)
                {
                    int i = (height - 1 - y) * width + x;
                    var prior = pixels[i];
                    pixels[i] = x == left || x == left + plateWidth - 1 || y == top || y == top + plateHeight - 1 ? border : new Color32((byte)(prior.r * .12f), (byte)(prior.g * .12f), (byte)(prior.b * .12f), 255);
                }

            for (int n = 0; n < text.Length; n++)
            {
                string decomposed = text[n].ToString().Normalize(NormalizationForm.FormD);
                if (!Glyphs.TryGetValue(decomposed[0], out var glyph))
                    glyph = Glyphs['?'];
                int x0 = left + padding + n * Advance * scale, y0 = top + padding;
                for (int y = 0; y < 7; y++)
                    for (int x = 0; x < GlyphWidth; x++)
                        if (glyph[y * Advance + x] == '1')
                            Dot(pixels, width, height, x0 + x * scale, y0 + (y + 2) * scale, scale, white, left, top, plateWidth, plateHeight);
                if (decomposed.Length > 1)
                {
                    string accent = decomposed[1] == '\u0301' ? "00010/00100" : decomposed[1] == '\u0300' ? "01000/00100" : decomposed[1] == '\u0302' ? "00100/01010" : decomposed[1] == '\u0308' ? "01010/00000" : "00000/00000";
                    for (int y = 0; y < 2; y++)
                        for (int x = 0; x < GlyphWidth; x++)
                            if (accent[y * Advance + x] == '1')
                                Dot(pixels, width, height, x0 + x * scale, y0 + y * scale, scale, white, left, top, plateWidth, plateHeight);
                    if (decomposed[1] == '\u0327')
                        Dot(pixels, width, height, x0 + 2 * scale, y0 + 9 * scale, scale, white, left, top, plateWidth, plateHeight);
                }
            }

            return new[]
            {
                left,
                top,
                plateWidth,
                plateHeight
            };
        }

        static bool Overlap(int x, int y, int width, int height, int[] rect, int gap) => x < rect[0] + rect[2] + gap && x + width + gap > rect[0] && y < rect[1] + rect[3] + gap && y + height + gap > rect[1];
        static void Dot(Color32[] pixels, int width, int height, int x0, int y0, int scale, Color32 color, int left, int top, int plateWidth, int plateHeight)
        {
            for (int y = y0; y < y0 + scale; y++)
                for (int x = x0; x < x0 + scale; x++)
                    if (x > left && x < left + plateWidth - 1 && y > top && y < top + plateHeight - 1)
                        pixels[(height - 1 - y) * width + x] = color;
        }
    }
}
