using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace Lotusim.Dataset
{
    public enum DatasetObjectSource
    {
        Lotusim,
        LocalPreview
    }

    [Serializable]
    public sealed class DatasetSeaPreset
    {
        public string name;
        public float windKmh, band0, band1, ripplesKmh, foam;
        public float directionDeg = 35, patchSizeM = 128;
        public float cameraMotionScale = 1;
    }

    [Serializable]
    public sealed class DatasetLightPreset
    {
        public string name;
        public string illuminant = "sun";
        public float relativeBearingDeg, elevationDeg, intensityLux, exposureEV100, temperatureKelvin;
    }

    [Serializable]
    public sealed class DatasetFlotationSettings
    {
        public bool enabled = true;
        public float sampleRadiusM = .35f, waterlineOffsetM = -.15f;
        public float heightResponsePerSecond = 6, tiltResponsePerSecond = 3, maxTiltDeg = 25;
        public void Validate()
        {
            if (!Finite(sampleRadiusM) || sampleRadiusM < .05f || sampleRadiusM > 10 || !Finite(waterlineOffsetM) || !Finite(heightResponsePerSecond) || heightResponsePerSecond <= 0 || heightResponsePerSecond > 100 || !Finite(tiltResponsePerSecond) || tiltResponsePerSecond <= 0 || tiltResponsePerSecond > 100 || !Finite(maxTiltDeg) || maxTiltDeg < 0 || maxTiltDeg > 60)
                throw new ArgumentException("Invalid visual flotation settings.");
        }

        static bool Finite(float value) => !float.IsNaN(value) && !float.IsInfinity(value);
    }

    [Serializable]
    public sealed class DatasetWaterOpticsSettings
    {
        [Tooltip("HDRP approximate visibility through water. Lower values obscure submerged objects more strongly; not a measured turbidity.")]
        public float absorptionDistanceM = .8f;
        public float maxRefractionDistanceM = .6f;
        public Color refractionColor = new Color(.06f, .24f, .30f, 1);
        public Color scatteringColor = new Color(.03f, .16f, .19f, 1);
        public void Validate()
        {
            if (!Positive(absorptionDistanceM) || absorptionDistanceM < .05f || absorptionDistanceM > 1000 || !Positive(maxRefractionDistanceM) || maxRefractionDistanceM > 100 || !ValidColor(refractionColor) || !ValidColor(scatteringColor))
                throw new ArgumentException("Invalid water optics settings.");
        }

        static bool Positive(float value) => !float.IsNaN(value) && !float.IsInfinity(value) && value > 0;
        internal static bool ValidColor(Color color) => Unit(color.r) && Unit(color.g) && Unit(color.b) && Unit(color.a);
        static bool Unit(float value) => !float.IsNaN(value) && !float.IsInfinity(value) && value >= 0 && value <= 1;
    }

    [Serializable]
    public sealed class DatasetLanternSettings
    {
        public bool enabled = true;
        public float periodSeconds = 2, flashSeconds = .25f, edgeFadeSeconds = .03f, phaseOffsetSeconds = 0;
        public Color color = new Color(1, .28f, .02f, 1);
        [Tooltip("HDR RGB emission multiplier. This is a visual setting, not a certified navigation-light intensity.")]
        public float peakEmissionIntensity = 1000;
        public float pointLightLumens = 3, pointLightRangeM = 2;
        public void Validate()
        {
            if (!Finite(periodSeconds) || periodSeconds <= 0 || periodSeconds > 60 || !Finite(flashSeconds) || flashSeconds <= 0 || flashSeconds >= periodSeconds || !Finite(edgeFadeSeconds) || edgeFadeSeconds < 0 || edgeFadeSeconds > flashSeconds / 2 || !Finite(phaseOffsetSeconds) || !Finite(peakEmissionIntensity) || peakEmissionIntensity < 0 || peakEmissionIntensity > 100000 || !Finite(pointLightLumens) || pointLightLumens < 0 || pointLightLumens > 10000 || !Finite(pointLightRangeM) || pointLightRangeM < .1f || pointLightRangeM > 100 || !DatasetWaterOpticsSettings.ValidColor(color))
                throw new ArgumentException("Invalid buoy lantern settings.");
        }

        static bool Finite(float value) => !float.IsNaN(value) && !float.IsInfinity(value);
    }

    [Serializable]
    public sealed class DatasetCameraMotionSettings
    {
        public bool enabled = true;
        public float rollAmplitudeDeg = 1.5f, pitchAmplitudeDeg = .8f;
        public float rollPeriodSeconds = 5.5f, pitchPeriodSeconds = 7;
        public void Validate()
        {
            if (!Finite(rollAmplitudeDeg) || rollAmplitudeDeg < 0 || rollAmplitudeDeg > 5 || !Finite(pitchAmplitudeDeg) || pitchAmplitudeDeg < 0 || pitchAmplitudeDeg > 5 || !Finite(rollPeriodSeconds) || rollPeriodSeconds < 1 || rollPeriodSeconds > 60 || !Finite(pitchPeriodSeconds) || pitchPeriodSeconds < 1 || pitchPeriodSeconds > 60)
                throw new ArgumentException("Invalid small-angle camera sway settings.");
        }

        // Smooth, seeded synthetic sway, not a pose received from a vessel.
        // x = local pitch, y = local roll, in degrees. Weighted sinusoids keep
        // both components bounded by their configured amplitudes.
        public Vector2 Angles(float elapsedSeconds, int seed, int conditionIndex, float seaScale)
        {
            if (!enabled)
                return Vector2.zero;
            float rollPhase = Phase(seed, conditionIndex, 0x73ac21u), pitchPhase = Phase(seed, conditionIndex, 0x321ab7u);
            float r = elapsedSeconds * 2 * Mathf.PI / rollPeriodSeconds, p = elapsedSeconds * 2 * Mathf.PI / pitchPeriodSeconds;
            float roll = rollAmplitudeDeg * seaScale * (.8f * Mathf.Sin(r + rollPhase) + .2f * Mathf.Sin(1.63f * r + .37f * rollPhase));
            float pitch = pitchAmplitudeDeg * seaScale * (.8f * Mathf.Sin(p + pitchPhase) + .2f * Mathf.Sin(1.27f * p + .61f * pitchPhase));
            return new Vector2(pitch, roll);
        }

        static float Phase(int seed, int conditionIndex, uint salt)
        {
            uint value = unchecked((uint)seed ^ (uint)conditionIndex * 0x9e3779b9u ^ salt);
            value ^= value >> 16;
            value = unchecked(value * 0x7feb352du);
            value ^= value >> 15;
            return (value & 0x00ffffffu) / 16777216f * (2 * Mathf.PI);
        }

        public static void ApplyPose(Camera camera, Vector3 nominalPosition, Quaternion nominalRotation, Vector2 pitchRollDeg)
        {
            camera.transform.SetPositionAndRotation(nominalPosition, nominalRotation * Quaternion.Euler(pitchRollDeg.x, 0, pitchRollDeg.y));
        }

        static bool Finite(float value) => !float.IsNaN(value) && !float.IsInfinity(value);
    }

    [Serializable]
    public sealed class DatasetAnnotationSettings
    {
        public bool enabled = true;
        [Tooltip("Optional class label on annotated previews. Empty uses the French name; machine category identifiers remain unchanged.")]
        public string displayName = "";
        public int reviewMinVisiblePixels = 16, reviewMinBoxSidePixels = 2;
        public DatasetRecognitionSettings recognition = new DatasetRecognitionSettings();
        public void Validate()
        {
            if (reviewMinVisiblePixels < 1 || reviewMinBoxSidePixels < 1 || reviewMinBoxSidePixels > 8192)
                throw new ArgumentException("Invalid annotation review thresholds.");
            if (recognition == null)
                recognition = new DatasetRecognitionSettings();
            recognition.Validate();
        }
    }

    [CreateAssetMenu(menuName = "LOTUSim/Dataset/Campaign")]
    public sealed class DatasetCampaignConfig : ScriptableObject
    {
        public DatasetObjectSource objectSource = DatasetObjectSource.Lotusim;
        public string rosNamespace = "lotusim", scenarioFile = "BuoyDatasetPilot.yaml", targetName = "Buoy_001";
        public string modelAddress = "buoy", category = "buoy";
        public int classId = 1;
        public bool launchScenario = true, stopOwnedScenarioOnCompletion = true;
        public GameObject localPreviewPrefab;
        public Vector3 localPreviewPosition = Vector3.zero;
        public string outputRoot = "artifacts/datasets";
        public int seed = 42, width = 1280, height = 720;
        public float verticalFovDeg = 50;
        public float[] distancesM =
        {
            10,
            25,
            50
        };
        public float[] azimuthsDeg =
        {
            0,
            90,
            180,
            270
        };
        public float[] elevationsDeg =
        {
            5,
            20
        };
        public DatasetFlotationSettings flotation = new DatasetFlotationSettings();
        public DatasetWaterOpticsSettings waterOptics = new DatasetWaterOpticsSettings();
        public DatasetLanternSettings lantern = new DatasetLanternSettings();
        public DatasetCameraMotionSettings cameraMotion = new DatasetCameraMotionSettings();
        public DatasetAnnotationSettings annotations = new DatasetAnnotationSettings();
        public DatasetSeaPreset[] seas =
        {
            new DatasetSeaPreset
            {
                name = "calm",
                windKmh = 0,
                band0 = 0,
                band1 = 0,
                ripplesKmh = 2,
                foam = 0,
                cameraMotionScale = .15f
            },
            new DatasetSeaPreset
            {
                name = "moderate",
                windKmh = 35,
                band0 = .7f,
                band1 = .6f,
                ripplesKmh = 10,
                foam = .2f,
                patchSizeM = 192,
                cameraMotionScale = .65f
            },
            new DatasetSeaPreset
            {
                name = "rough",
                windKmh = 70,
                band0 = 1,
                band1 = .9f,
                ripplesKmh = 18,
                foam = .5f,
                patchSizeM = 256
            }
        };
        public DatasetLightPreset[] lights =
        {
            new DatasetLightPreset
            {
                name = "front",
                relativeBearingDeg = 0,
                elevationDeg = 45,
                intensityLux = 80000,
                exposureEV100 = 13,
                temperatureKelvin = 5600
            },
            new DatasetLightPreset
            {
                name = "backlight",
                relativeBearingDeg = 180,
                elevationDeg = 12,
                intensityLux = 30000,
                exposureEV100 = 12.5f,
                temperatureKelvin = 4500
            }
        };
        public int samplesPerCondition = 3, settleRenderedFrames = 60, simulationFps = 30;
        public float sampleIntervalSeconds = 1, connectionTimeoutSeconds = 45, objectTimeoutSeconds = 45, renderTimeoutSeconds = 45;
        public bool shuffleConditions = false;
        public void Validate()
        {
            if (flotation == null)
                throw new ArgumentException("Missing flotation settings.");
            flotation.Validate();
            if (waterOptics == null || lantern == null)
                throw new ArgumentException("Missing water optics or lantern settings.");
            waterOptics.Validate();
            lantern.Validate();
            if (cameraMotion == null)
                throw new ArgumentException("Missing camera motion settings.");
            cameraMotion.Validate();
            if (annotations == null)
                throw new ArgumentException("Missing annotation settings.");
            annotations.Validate();
            if (width < 16 || height < 16 || width > 8192 || height > 8192 || !Finite(verticalFovDeg) || verticalFovDeg < 5 || verticalFovDeg > 120)
                throw new ArgumentException("Invalid capture resolution or field of view.");
            if (samplesPerCondition < 1 || samplesPerCondition > 1000 || settleRenderedFrames < 2 || simulationFps < 1 || simulationFps > 120 || !Finite(sampleIntervalSeconds) || sampleIntervalSeconds <= 0 || !Finite(connectionTimeoutSeconds) || connectionTimeoutSeconds <= 0 || !Finite(objectTimeoutSeconds) || objectTimeoutSeconds <= 0 || !Finite(renderTimeoutSeconds) || renderTimeoutSeconds <= 0)
                throw new ArgumentException("Invalid sample count, frame rate or timeout.");
            CheckAxis(distancesM, v => v > 0, "distances");
            CheckAxis(azimuthsDeg, v => v >= 0 && v < 360, "azimuths");
            CheckAxis(elevationsDeg, v => v > -85 && v < 85, "elevations");
            if (seas == null || seas.Length == 0 || lights == null || lights.Length == 0)
                throw new ArgumentException("Missing environment presets.");
            if (seas.Any(s => s == null || string.IsNullOrWhiteSpace(s.name) || !Finite(s.windKmh) || s.windKmh < 0 || !Unit(s.band0) || !Unit(s.band1) || !Finite(s.ripplesKmh) || s.ripplesKmh < 0 || !Unit(s.foam) || !Finite(s.directionDeg) || !Finite(s.patchSizeM) || s.patchSizeM < 25 || !Unit(s.cameraMotionScale)))
                throw new ArgumentException("Invalid sea preset. Amplitude multipliers are dimensionless, not metres.");
            if (lights.Any(l => l == null || string.IsNullOrWhiteSpace(l.name) || !Finite(l.relativeBearingDeg) || !Finite(l.elevationDeg) || l.elevationDeg <= 0 || l.elevationDeg >= 90 || !Finite(l.intensityLux) || l.intensityLux <= 0 || !Finite(l.exposureEV100) || !Finite(l.temperatureKelvin) || l.temperatureKelvin < 1500 || l.temperatureKelvin > 20000))
                throw new ArgumentException("Invalid light preset.");
            if (seas.Select(s => s.name).Distinct().Count() != seas.Length || lights.Select(l => l.name).Distinct().Count() != lights.Length)
                throw new ArgumentException("Preset names must be unique.");
            if (string.IsNullOrWhiteSpace(targetName) || string.IsNullOrWhiteSpace(modelAddress) || string.IsNullOrWhiteSpace(category) || string.IsNullOrWhiteSpace(outputRoot) || classId < 0)
                throw new ArgumentException("Missing target identity or output path.");
            if (objectSource == DatasetObjectSource.Lotusim && (string.IsNullOrWhiteSpace(rosNamespace) || string.IsNullOrWhiteSpace(scenarioFile)))
                throw new ArgumentException("Missing ROS namespace or scenario filename.");
            if (ConditionCount() > 100000)
                throw new ArgumentException("Campaign too large for this pilot.");
        }

        static bool Finite(float value) => !float.IsNaN(value) && !float.IsInfinity(value);
        static bool Unit(float value) => Finite(value) && value >= 0 && value <= 1;
        static void CheckAxis(float[] values, Func<float, bool> allowed, string label)
        {
            if (values == null || values.Length == 0 || values.Any(v => !Finite(v) || !allowed(v)) || values.Distinct().Count() != values.Length)
                throw new ArgumentException("Invalid or duplicate " + label);
        }

        public int ConditionCount() => checked(distancesM.Length * azimuthsDeg.Length * elevationsDeg.Length * seas.Length * lights.Length);
        public int ImageCount() => checked(ConditionCount() * samplesPerCondition);
        public List<DatasetCondition> Conditions()
        {
            Validate();
            var result = new List<DatasetCondition>();
            foreach (var sea in seas)
                foreach (var light in lights)
                    foreach (float distance in distancesM)
                        foreach (float azimuth in azimuthsDeg)
                            foreach (float elevation in elevationsDeg)
                                result.Add(new DatasetCondition { index = result.Count, distanceM = distance, azimuthDeg = azimuth, elevationDeg = elevation, sea = sea, light = light });
            if (shuffleConditions)
            {
                var random = new System.Random(seed);
                for (int i = result.Count - 1; i > 0; i--)
                {
                    int j = random.Next(i + 1);
                    var swap = result[i];
                    result[i] = result[j];
                    result[j] = swap;
                }
            }

            return result;
        }

        public static Vector3 OrbitOffset(float distance, float azimuth, float elevation)
        {
            float a = azimuth * Mathf.Deg2Rad, e = elevation * Mathf.Deg2Rad;
            return distance * new Vector3(Mathf.Sin(a) * Mathf.Cos(e), Mathf.Sin(e), Mathf.Cos(a) * Mathf.Cos(e));
        }
    }

    [Serializable]
    public sealed class DatasetCondition
    {
        public int index;
        public float distanceM, azimuthDeg, elevationDeg;
        public DatasetSeaPreset sea;
        public DatasetLightPreset light;
    }
}
