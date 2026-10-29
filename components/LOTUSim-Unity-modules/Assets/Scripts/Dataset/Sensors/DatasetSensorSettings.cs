using System;
using System.Linq;
using UnityEngine;

namespace Lotusim.Dataset
{
    [Serializable]
    public sealed class DatasetThermalClassProfile
    {
        public string category;
        public float temperatureC = 26, emissivity = .92f;
    }

    [Serializable]
    public sealed class DatasetSensorSettings
    {
        public bool thermal, nightVision, blackHot;
        public float thermalMinC = 5, thermalMaxC = 55, waterTemperatureC = 18, skyTemperatureC = -20, backgroundTemperatureC = 22;
        public float nightGain = 5, nightGamma = .8f, nightNoise = .012f, nightVignette = .25f;
        public Color nightTint = new Color(.12f, 1, .22f, 1);
        public DatasetThermalClassProfile[] thermalClasses = Defaults();
        public bool Enabled => thermal || nightVision;

        public void Validate()
        {
            if (!Range(thermalMinC, -100, 200) || !Range(thermalMaxC, thermalMinC + 1, 300) || !Range(waterTemperatureC, -10, 60) || !Range(skyTemperatureC, -100, 60) || !Range(backgroundTemperatureC, -50, 120) || !Range(nightGain, .1f, 30) || !Range(nightGamma, .3f, 2) || !Range(nightNoise, 0, .1f) || !Range(nightVignette, 0, .8f) || !Range(nightTint.r, 0, 1) || !Range(nightTint.g, 0, 1) || !Range(nightTint.b, 0, 1) || thermalClasses == null || thermalClasses.Any(c => c == null || string.IsNullOrWhiteSpace(c.category) || !Range(c.temperatureC, -100, 300) || !Range(c.emissivity, .05f, 1)) || thermalClasses.Select(c => c.category).Distinct().Count() != thermalClasses.Length)
                throw new ArgumentException("Invalid synthetic thermal / night-vision settings.");
        }

        public DatasetThermalClassProfile Profile(string category) => thermalClasses.FirstOrDefault(c => c.category == category) ?? new DatasetThermalClassProfile
        {
            category = category,
            temperatureC = backgroundTemperatureC,
            emissivity = .92f
        };
        public static DatasetThermalClassProfile[] Defaults()
        {
            string[] names =
            {
                "buoy",
                "drone",
                "helicopter",
                "airplane",
                "bird",
                "fishing_trawler",
                "container_ship",
                "motor_yacht",
                "speedboat",
                "jetski",
                "ferry",
                "sailboat"
            };
            float[] temperatures =
            {
                20,
                35,
                40,
                32,
                39,
                26,
                27,
                26,
                28,
                30,
                27,
                23
            };
            return names.Select((n, i) => new DatasetThermalClassProfile { category = n, temperatureC = temperatures[i], emissivity = n == "bird" ? .98f : .92f }).ToArray();
        }

        public static float ApparentTemperature(float temperatureC, float emissivity, float environmentC)
        {
            double t = temperatureC + 273.15, e = environmentC + 273.15;
            return (float)(Math.Pow(emissivity * Math.Pow(t, 4) + (1 - emissivity) * Math.Pow(e, 4), .25) - 273.15);
        }

        static bool Range(float v, float a, float b) => !float.IsNaN(v) && !float.IsInfinity(v) && v >= a && v <= b;
    }

    [Serializable]
    public sealed class DatasetSensorFrame
    {
        public string mode, imageFile, overlayFile, model;
        public bool calibrated = false, geometricallyAligned = true;
        public int width, height, unityFrame;
    }
}
