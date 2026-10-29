using System;
using System.Collections.Generic;
using System.Linq;
using Lotusim.Dataset;
using UnityEditor;
using UnityEngine;

namespace Lotusim.EditorTools
{
    public static class DatasetBoatVariantTests
    {
        [MenuItem("LOTUSim/Models/External CC-BY boats/Validate seeded dataset variants")]
        public static void Run()
        {
            var source = AssetDatabase.LoadAssetAtPath<DatasetSequenceConfig>(DatasetLotusimSceneBuilder.ConfigPath);
            if (source == null)
                throw new InvalidOperationException("Connected dataset configuration missing.");
            var copy = UnityEngine.Object.Instantiate(source);
            var selected = new HashSet<string>();
            try
            {
                for (int seed = 0; seed < 40; seed++)
                {
                    copy.seed = seed;
                    MarineOpenBoatsBuilder.ConfigureVariants(copy);
                    var variant = copy.MakePlan();
                    if (JsonUtility.ToJson(variant) != JsonUtility.ToJson(copy.MakePlan()))
                        throw new Exception("Non-reproducible variant plan");
                    string yaml = DatasetLotusimScenario.Yaml(copy, variant);
                    foreach (var e in variant.events)
                    {
                        string model = DatasetBoatVariants.Resolve(copy.classes[e.classIndex], e).name;
                        selected.Add(model);
                        if (!yaml.Contains("model: " + model + "\n"))
                            throw new Exception("Renderer/Gazebo model mismatch");
                    }

                    foreach (var c in copy.classes)
                        c.prefabVariants = Array.Empty<GameObject>();
                    var baseline = copy.MakePlan();
                    for (int i = 0; i < variant.events.Length; i++)
                    {
                        var a = variant.events[i];
                        var b = baseline.events[i];
                        if (a.instance != b.instance || a.classIndex != b.classIndex || a.centerPosition != b.centerPosition || a.velocity != b.velocity || a.startSeconds != b.startSeconds || a.endSeconds != b.endSeconds || a.phase != b.phase)
                            throw new Exception("Appearance selection changed trajectory/labels: " + a.instance);
                    }

                    if (JsonUtility.ToJson(variant.sea) != JsonUtility.ToJson(baseline.sea) || JsonUtility.ToJson(variant.light) != JsonUtility.ToJson(baseline.light))
                        throw new Exception("Appearance selection changed weather");
                }

                // This fixture expects the supplied connected config to contain
                // the three affected categories; counts remain user-editable.
                foreach (string model in DatasetBoatVariants.Models)
                {
                    int index = Array.IndexOf(DatasetBoatVariants.Models, model);
                    if (copy.classes.Any(c => c.category == DatasetBoatVariants.Categories[index] && c.count > 0) && !selected.Contains(model))
                        throw new Exception("Variant not reachable in regression fixture: " + model);
                }
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(copy);
            }

            Debug.Log("[Open Boats] PASS 40 seeds: reproducible appearance, unchanged class/track IDs, trajectories and weather; matching renderer/Gazebo assets.");
        }
    }
}
