using System;
using System.IO;
using System.Linq;
using System.Reflection;
using Lotusim.Dataset;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Lotusim.EditorTools
{
    public static class DatasetManualCampaignTests
    {
        [MenuItem("LOTUSim/Dataset/Manual campaigns/Validate importer without launching")]
        public static void Run()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
                throw new InvalidOperationException("Run manual plan tests outside Play.");
            var original = AssetDatabase.LoadAssetAtPath<DatasetSequenceConfig>(DatasetLotusimSceneBuilder.ConfigPath);
            if (original == null)
                throw new InvalidOperationException("Connected template missing.");
            string before = JsonUtility.ToJson(original);
            var request = new DatasetManualCampaignRequest
            {
                schema = "lotusim-campaign-settings-1",
                name = "Manual contract fixture",
                engine = "unity",
                scene = "maritime_manual",
                seed = 7,
                totalImages = 2,
                camera = new DatasetManualCamera
                {
                    width = 1280,
                    height = 720,
                    verticalFovDeg = 55,
                    farClipM = 80000,
                    station = "bridge",
                    viewHeadingDeg = 40,
                    viewDownPitchDeg = 2
                },
                observer = new DatasetManualObserver
                {
                    speedMps = 4,
                    headingDeg = 35,
                    rollMaxDeg = 7,
                    pitchMaxDeg = 4
                },
                sensors = new DatasetManualSensors()
            };
            var block = new DatasetManualBlock
            {
                id = "fixture",
                name = "Fixture",
                images = 2,
                environment = new DatasetManualEnvironment
                {
                    timeOfDay = "day",
                    cloudCover = .4f,
                    rainIntensity = .1f,
                    waveHeightM = 4
                },
                objects = new[]
                {
                    new DatasetManualObjectRequest
                    {
                        id = "buoy1",
                        model = "buoy",
                        count = 1,
                        distanceM = 120,
                        bearingDeg = 5,
                        headingDeg = 20
                    },
                    new DatasetManualObjectRequest
                    {
                        id = "boat1",
                        model = "sailboat",
                        count = 1,
                        distanceM = 450,
                        bearingDeg = -10,
                        speedMps = 2,
                        headingDeg = 90
                    }
                }
            };
            request.blocks = new[]
            {
                block
            };
            string json = JsonUtility.ToJson(request), sha = DatasetTrafficPlanBundle.Hash(json);
            var method = typeof(DatasetManualCampaignBuilder).GetMethod("BuildJob", BindingFlags.Static | BindingFlags.NonPublic);
            // Read the existing catalogue using the builder's private DTO, so
            // this test exercises exactly the production import path.
            var catalogueType = typeof(DatasetManualCampaignBuilder).GetNestedType("Catalogue", BindingFlags.NonPublic);
            var catalogue = JsonUtility.FromJson(File.ReadAllText(Path.Combine(DatasetManualCampaignBuilder.CoreRoot, "assets/scenarios/catalogs/traffic_assets.json")), catalogueType);
            var assets = catalogueType.GetField("assets").GetValue(catalogue);
            DatasetSequenceConfig c = null;
            DatasetManualPlanBundle bundle = null;
            try
            {
                var job = method.Invoke(null, new object[] { original, request, block, 0, 0, "contract_fixture", sha, json, assets });
                c = (DatasetSequenceConfig)job.GetType().GetField("config").GetValue(job);
                bundle = c.manualPlan;
                var p = c.MakePlan();
                Check(c.ImageCount == 1 && c.ShouldCapture(0) && !c.ShouldCapture(1), "one exact independent capture");
                Check(p.manual.independentImage && !p.manual.continuousVideo && p.traffic == null, "manual/traffic separation");
                Check(p.events.Length == 2 && p.maxActive == 2, "exact selected object count");
                var buoy = p.events.Single(e => e.modelName == "buoy");
                var delta = buoy.centerPosition - c.ObserverNominal(0);
                Check(Mathf.Abs(new Vector2(delta.x, delta.z).magnitude - 120) < .001f, "horizontal range remains exact");
                Check(buoy.centerPosition.y == 0 && buoy.velocity == Vector3.zero, "moored surface placement");
                Check(Mathf.Abs(p.events.Single(e => e.modelName == "sailboat").velocity.magnitude - 2) < .001f, "catalogue-limited requested speed");
                Check(p.lightingPhases.Length == 1 && p.manual.environment.waveHeightM == 4 && !p.manual.waveHeightCalibrated, "explicit weather/light provenance");
                Check(c.width == 1280 && c.height == 720 && c.verticalFovDeg == 55, "requested camera resolution/FOV");
                string valid = bundle.contentSha256;
                bundle.contentSha256 = "tampered";
                bool rejected = false;
                try
                {
                    c.MakePlan();
                }
                catch (InvalidOperationException)
                {
                    rejected = true;
                }

                bundle.contentSha256 = valid;
                Check(rejected, "tampered immutable bundle refused");
                Check(JsonUtility.ToJson(original) == before, "original configuration untouched");
                Debug.Log("[Manual Campaign Tests] PASS 10 contracts. No scene writes, Play, ROS connection, service request or simulation launch.");
            }
            finally
            {
                if (c != null)
                    Object.DestroyImmediate(c);
                if (bundle != null)
                    Object.DestroyImmediate(bundle);
            }
        }

        static void Check(bool condition, string contract)
        {
            if (!condition)
                throw new Exception("Manual campaign contract failed: " + contract);
        }
    }
}
