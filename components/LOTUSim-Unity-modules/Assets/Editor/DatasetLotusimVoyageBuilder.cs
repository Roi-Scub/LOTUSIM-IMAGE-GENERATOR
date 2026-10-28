using System;
using System.Linq;
using Lotusim.Dataset;
using UnityEditor;
using UnityEngine;

namespace Lotusim.EditorTools
{
    public static partial class DatasetLotusimSceneBuilder
    {
        public static void ConfigureVoyage(DatasetSequenceConfig config)
        {
            config.observerTurnDeg = -8;
            config.observerDeckCamera = true;
            config.observerDeckOffsetM = new Vector3(60, 8.85f, -3);
            config.observerHeightM = 8.85f;
            config.viewHeadingDeg = 15;
            config.requireSwell = true;
            config.seaEvolution = new DatasetSeaEvolution
            {
                enabled = true
            };
            config.maxActiveObjects = Mathf.Max(config.maxActiveObjects, 20);
            config.observerHullHalfExtentsM = new Vector3(15, 43, 78);
            float[] near =
            {
                110,
                650,
                120,
                100,
                75,
                400,
                110
            }, far =
            {
                350,
                1400,
                400,
                320,
                230,
                900,
                340
            };
            float[] slow =
            {
                2,
                3,
                4,
                8,
                12,
                6,
                1.5f
            }, fast =
            {
                4.5f,
                6,
                9,
                14,
                20,
                10,
                3.5f
            };
            var classes = config.classes.ToList();
            for (int i = 0; i < 7; i++)
            {
                string name = MarineVesselCatalog.Models[i];
                var category = classes.FirstOrDefault(c => c.category == name);
                if (category == null)
                {
                    if (classes.Any(c => c.classId == i + 6))
                        throw new InvalidOperationException("Marine category ID already used: " + (i + 6));
                    category = new DatasetEncounterClass
                    {
                        category = name,
                        displayName = MarineVesselCatalog.DisplayNames[i],
                        classId = i + 6
                    };
                    classes.Add(category);
                }

                category.prefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/" + name + ".prefab");
                if (category.prefab == null)
                    throw new InvalidOperationException("Missing marine prefab: " + name);
                category.count = 1;
                category.moored = false;
                category.altitudeM = Vector2.zero;
                category.distanceM = new Vector2(near[i], far[i]);
                category.speedMps = new Vector2(slow[i], fast[i]);
                category.separationM = Mathf.Max(5, MarineVesselCatalog.Parameters(i).lengthM * .55f);
            }

            foreach (var c in classes)
            {
                if (c.category == "buoy")
                    c.distanceM = new Vector2(65, 180);
                if (c.category == "bird")
                    c.distanceM = new Vector2(65, 180);
                if (c.category == "drone")
                    c.distanceM = new Vector2(75, 180);
            }

            config.classes = classes.ToArray();
            config.connectedVoyageVersion = 1;
            config.Validate();
            config.MakePlan();
            EditorUtility.SetDirty(config);
            Debug.Log("[LOTUSim Voyage] Evolving rough swell, seven moving vessel classes and a gentle port turn enabled. FREMM foredeck eye position: 60 / 8.85 / -3 m, gaze 15 deg starboard. Capture count/resolution preserved.");
        }

        static GameObject EnsureDeckObserver(GameObject prefab)
        {
            if (prefab.GetComponent<MarineVesselWaveMotion>() != null && prefab.transform.Find(MarineVesselWaveMotion.VisualChildName + "/DatasetDeckGuardrails_v2") != null)
                return prefab;
            var root = PrefabUtility.LoadPrefabContents(ObserverPath);
            try
            {
                var visual = root.transform.Find(MarineVesselWaveMotion.VisualChildName);
                if (visual == null)
                {
                    var imported = root.transform.Find("FREMM");
                    if (imported == null)
                        throw new InvalidOperationException("FREMM visual child missing; no replacement was made.");
                    visual = new GameObject(MarineVesselWaveMotion.VisualChildName).transform;
                    visual.SetParent(root.transform, false);
                    imported.SetParent(visual, false);
                }

                var body = root.GetComponent<Rigidbody>();
                if (body == null)
                    body = root.AddComponent<Rigidbody>();
                body.isKinematic = true;
                body.useGravity = false;
                var motion = root.GetComponent<MarineVesselWaveMotion>();
                if (motion == null)
                    motion = root.AddComponent<MarineVesselWaveMotion>();
                motion.visual = visual;
                motion.parameters = new MarineVesselParameters
                {
                    lengthM = 142,
                    beamM = 20,
                    draftM = 6,
                    blockCoefficient = .5f,
                    maxRollDeg = 3.5f,
                    maxPitchDeg = 2.5f,
                    heaveFrequencyScale = .75f
                };
                var oldRails = visual.Find("DatasetDeckGuardrails");
                if (oldRails != null)
                    UnityEngine.Object.DestroyImmediate(oldRails.gameObject);
                var rails = visual.Find("DatasetDeckGuardrails_v2");
                if (rails == null)
                {
                    rails = new GameObject("DatasetDeckGuardrails_v2").transform;
                    rails.SetParent(visual, false);
                    const string path = "Assets/Dataset/FremmObserverMaterials/DeckGuardrails.mat";
                    var material = AssetDatabase.LoadAssetAtPath<Material>(path);
                    if (material == null)
                    {
                        material = new Material(Shader.Find("HDRP/Lit"))
                        {
                            name = "FREMM painted deck guardrails"
                        };
                        material.SetColor("_BaseColor", new Color(.42f, .47f, .49f));
                        material.SetFloat("_Metallic", .35f);
                        material.SetFloat("_Smoothness", .4f);
                        UnityEngine.Rendering.HighDefinition.HDMaterial.ValidateMaterial(material);
                        AssetDatabase.CreateAsset(material, path);
                    }

                    // Added observation-area guardrails, not a claim about the
                    // exact equipment layout of a real FREMM. Deck sampled on
                    // the imported mesh: ~7.06 m at x=60, z=-4.
                    for (int i = 0; i <= 5; i++)
                        Tube(rails, material, new Vector3(56 + i * 2, 7.00f + i * .032f, -4.5f + i * .10f), new Vector3(56 + i * 2, 8.10f + i * .032f, -4.5f + i * .10f), .022f);
                    for (int level = 0; level < 3; level++)
                        Tube(rails, material, new Vector3(56, 7.35f + level * .375f, -4.5f), new Vector3(66, 7.51f + level * .375f, -4), .019f);
                }

                return PrefabUtility.SaveAsPrefabAsset(root, ObserverPath);
            }
            finally
            {
                PrefabUtility.UnloadPrefabContents(root);
            }
        }

        static void Tube(Transform parent, Material material, Vector3 a, Vector3 b, float radius)
        {
            var tube = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            tube.name = "Deck rail";
            tube.transform.SetParent(parent, false);
            tube.transform.localPosition = (a + b) * .5f;
            tube.transform.localRotation = Quaternion.FromToRotation(Vector3.up, b - a);
            tube.transform.localScale = new Vector3(radius * 2, (b - a).magnitude * .5f, radius * 2);
            UnityEngine.Object.DestroyImmediate(tube.GetComponent<Collider>());
            tube.GetComponent<MeshRenderer>().sharedMaterial = material;
        }
    }
}
