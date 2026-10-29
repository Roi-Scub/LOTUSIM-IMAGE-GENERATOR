using System;
using System.Linq;
using Lotusim.Dataset;
using UnityEditor;
using UnityEngine;

namespace Lotusim.EditorTools
{
    public static class DatasetPilotTests
    {
        [MenuItem("LOTUSim/Dataset/Validate campaign planning")]
        public static void Run()
        {
            var config = ScriptableObject.CreateInstance<DatasetCampaignConfig>();
            try
            {
                Check(config);
                CheckFlotation();
                CheckOpticsAndLantern();
                CheckCameraSway();
                Debug.Log("[Dataset] Planning/flotation/optics/lantern/camera tests PASS: 144 conditions, 432 unique samples, orbit and flotation geometry, water settings, flash cadence and bounded camera sway.");
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(config);
            }
        }

        public static void Check(DatasetCampaignConfig config)
        {
            config.Validate();
            var conditions = config.Conditions();
            Assert(conditions.Count == 144 && config.ImageCount() == 432, "Default campaign size");
            Assert(conditions.Select(c => c.index).Distinct().Count() == 144, "Unique condition IDs");
            Assert(conditions.SelectMany(c => Enumerable.Range(0, config.samplesPerCondition).Select(s => c.index + "_" + s)).Distinct().Count() == 432, "Unique image IDs");
            foreach (var condition in conditions)
            {
                var offset = DatasetCampaignConfig.OrbitOffset(condition.distanceM, condition.azimuthDeg, condition.elevationDeg);
                Assert(Mathf.Abs(offset.magnitude - condition.distanceM) < .0001f, "True orbit distance");
                Assert(Mathf.Abs(Mathf.Asin(offset.y / offset.magnitude) * Mathf.Rad2Deg - condition.elevationDeg) < .0001f, "True orbit elevation");
            }

            config.shuffleConditions = true;
            int[] order = config.Conditions().Select(c => c.index).ToArray();
            Assert(order.SequenceEqual(config.Conditions().Select(c => c.index)), "Seed replay");
            config.seed++;
            Assert(!order.SequenceEqual(config.Conditions().Select(c => c.index)), "Different seeds");
            config.distancesM = new[]
            {
                float.NaN
            };
            bool rejected = false;
            try
            {
                config.Validate();
            }
            catch (ArgumentException)
            {
                rejected = true;
            }

            Assert(rejected, "NaN rejection");
        }

        public static void CheckFlotation()
        {
            Assert(Vector3.Distance(BuoyWaveMotion.NormalFromHeights(2, 2, 2, 2, .35f), Vector3.up) < 1e-6f, "Flat water normal");
            var slope = BuoyWaveMotion.NormalFromHeights(-.35f, .35f, 0, 0, .35f);
            Assert(Vector3.Distance(slope, new Vector3(-1, 1, 0).normalized) < 1e-6f, "X slope normal");
            Assert(Vector3.Distance(BuoyWaveMotion.NormalFromHeights(0, 0, -.35f, .35f, .35f), new Vector3(0, 1, -1).normalized) < 1e-6f, "Z slope normal");
            var limited = BuoyWaveMotion.ClampNormal(slope, 25);
            Assert(Mathf.Abs(limited.y - Mathf.Cos(25 * Mathf.Deg2Rad)) < 1e-6f && Mathf.Abs(limited.magnitude - 1) < 1e-6f, "Tilt clamp 25 degrees");
            Assert(Vector3.Distance(BuoyWaveMotion.ClampNormal(slope, 0), Vector3.up) < 1e-6f, "Zero tilt setting");
            Assert(Vector3.Distance(BuoyWaveMotion.ClampNormal(Vector3.up, 25), Vector3.up) < 1e-6f, "No tilt on calm water");
            float full = BuoyWaveMotion.ResponseBlend(6, 1f / 30), half = BuoyWaveMotion.ResponseBlend(6, 1f / 60);
            Assert(Mathf.Abs(full - (1 - (1 - half) * (1 - half))) < 1e-6f, "Response independent of frame subdivision");
            Assert(BuoyWaveMotion.ResponseBlend(6, 0) == 0, "Paused time does not move the buoy");
            bool rejected = false;
            try
            {
                new DatasetFlotationSettings
                {
                    sampleRadiusM = 0
                }.Validate();
            }
            catch (ArgumentException)
            {
                rejected = true;
            }

            Assert(rejected, "Zero probe radius rejected");
            rejected = false;
            try
            {
                new DatasetFlotationSettings
                {
                    maxTiltDeg = float.NaN
                }.Validate();
            }
            catch (ArgumentException)
            {
                rejected = true;
            }

            Assert(rejected, "Nonfinite flotation rejected");
            var settings = new DatasetFlotationSettings
            {
                enabled = false
            };
            settings.Validate();
            Assert(!settings.enabled, "Static baseline remains selectable");
        }

        public static void CheckOpticsAndLantern()
        {
            new DatasetWaterOpticsSettings().Validate();
            bool rejected = false;
            try
            {
                new DatasetWaterOpticsSettings
                {
                    absorptionDistanceM = 0
                }.Validate();
            }
            catch (ArgumentException)
            {
                rejected = true;
            }

            Assert(rejected, "Zero absorption distance rejected");
            rejected = false;
            try
            {
                new DatasetWaterOpticsSettings
                {
                    refractionColor = new Color(float.NaN, 0, 0)
                }.Validate();
            }
            catch (ArgumentException)
            {
                rejected = true;
            }

            Assert(rejected, "Nonfinite water color rejected");
            var signal = new DatasetLanternSettings();
            signal.Validate();
            Assert(BuoyLanternFlash.EvaluateLevel(.1f, signal) == 1, "Flash on plateau");
            Assert(BuoyLanternFlash.EvaluateLevel(1, signal) == 0, "Dark interval");
            Assert(Mathf.Abs(BuoyLanternFlash.EvaluateLevel(.015f, signal) - .5f) < 1e-5f, "Flash fade in");
            Assert(Mathf.Abs(BuoyLanternFlash.EvaluateLevel(.235f, signal) - .5f) < 1e-5f, "Flash fade out");
            Assert(Mathf.Abs(BuoyLanternFlash.EvaluateLevel(2.1f, signal) - 1) < 1e-5f, "Periodic flash");
            signal.phaseOffsetSeconds = .1f;
            Assert(BuoyLanternFlash.EvaluateLevel(0, signal) == 1, "Configured phase offset");
            signal.enabled = false;
            Assert(BuoyLanternFlash.EvaluateLevel(.1f, signal) == 0, "Disabled light is dark");
            rejected = false;
            try
            {
                new DatasetLanternSettings
                {
                    flashSeconds = 2
                }.Validate();
            }
            catch (ArgumentException)
            {
                rejected = true;
            }

            Assert(rejected, "Flash must leave a dark interval");
            rejected = false;
            try
            {
                new DatasetLanternSettings
                {
                    edgeFadeSeconds = 1
                }.Validate();
            }
            catch (ArgumentException)
            {
                rejected = true;
            }

            Assert(rejected, "Invalid flash ramp rejected");
            Assert(new DatasetFlotationSettings().waterlineOffsetM < 0, "Default buoy is lowered below the sampled surface");
        }

        public static void CheckCameraSway()
        {
            var motion = new DatasetCameraMotionSettings();
            motion.Validate();
            foreach (float scale in new[]
            {
                0f,
                .15f,
                .65f,
                1f
            }

            )
                for (int i = 0; i < 2000; i++)
                {
                    var angles = motion.Angles(i * .03f, 42, 17, scale);
                    Assert(Mathf.Abs(angles.x) <= motion.pitchAmplitudeDeg * scale + 1e-5f, "Pitch amplitude bounded");
                    Assert(Mathf.Abs(angles.y) <= motion.rollAmplitudeDeg * scale + 1e-5f, "Roll amplitude bounded");
                }

            Assert(motion.Angles(5, 42, 17, 1) == motion.Angles(5, 42, 17, 1), "Camera seed/time replay");
            Assert((motion.Angles(5, 42, 17, 1) - motion.Angles(5, 43, 17, 1)).magnitude > .001f, "Camera seed changes phases");
            Assert((motion.Angles(5, 42, 17, 1) - motion.Angles(5, 42, 18, 1)).magnitude > .001f, "Camera condition changes phases");
            Assert((motion.Angles(5, 42, 17, .15f) - motion.Angles(5, 42, 17, 1) * .15f).magnitude < 1e-5f, "Camera sea scaling");
            Assert((motion.Angles(5.001f, 42, 17, 1) - motion.Angles(5, 42, 17, 1)).magnitude < .01f, "Smooth camera movement");
            motion.enabled = false;
            Assert(motion.Angles(5, 42, 17, 1) == Vector2.zero, "Camera sway can be disabled");
            bool rejected = false;
            try
            {
                new DatasetCameraMotionSettings
                {
                    rollAmplitudeDeg = 6
                }.Validate();
            }
            catch (ArgumentException)
            {
                rejected = true;
            }

            Assert(rejected, "Large camera motion rejected in small-angle pilot");
            rejected = false;
            try
            {
                new DatasetCameraMotionSettings
                {
                    pitchPeriodSeconds = float.NaN
                }.Validate();
            }
            catch (ArgumentException)
            {
                rejected = true;
            }

            Assert(rejected, "Nonfinite camera period rejected");
        }

        static void Assert(bool valid, string label)
        {
            if (!valid)
                throw new InvalidOperationException("Dataset test failed: " + label);
        }
    }
}
