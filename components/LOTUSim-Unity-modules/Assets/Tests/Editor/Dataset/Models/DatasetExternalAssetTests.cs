using System;
using System.Linq;
using Lotusim.Dataset;
using UnityEditor;
using UnityEngine;

namespace Lotusim.EditorTools
{
    public static class DatasetExternalAssetTests
    {
        [MenuItem("LOTUSim/Models/External objects CC-BY/Validate motion and animation invariants")]
        public static void Run()
        {
            MarineOpenObjectsBuilder.Validate();
            var source = AssetDatabase.LoadAssetAtPath<DatasetSequenceConfig>(DatasetLotusimSceneBuilder.ConfigPath);
            var copy = UnityEngine.Object.Instantiate(source);
            try
            {
                MarineOpenObjectsBuilder.ConfigureVariants(copy);
                for (int seed = 0; seed < 100; seed++)
                {
                    copy.seed = seed;
                    var plan = copy.MakePlan();
                    if (JsonUtility.ToJson(plan) != JsonUtility.ToJson(copy.MakePlan()))
                        throw new Exception("Appearance is not reproducible");
                    foreach (var e in plan.events)
                        if (!DatasetLotusimScenario.Yaml(copy, plan).Contains("model: " + e.modelName + "\n"))
                            throw new Exception("Missing LOTUSim mapping");
                    var lists = copy.classes.Select(c => c.prefabVariants).ToArray();
                    foreach (var c in copy.classes)
                        c.prefabVariants = Array.Empty<GameObject>();
                    var baseline = copy.MakePlan();
                    for (int i = 0; i < plan.events.Length; i++)
                    {
                        var a = plan.events[i];
                        var b = baseline.events[i];
                        if (a.instance != b.instance || a.classIndex != b.classIndex || a.velocity != b.velocity || a.centerPosition != b.centerPosition || a.startSeconds != b.startSeconds || a.endSeconds != b.endSeconds || a.phase != b.phase)
                            throw new Exception("Appearance changed motion/identity");
                    }

                    if (JsonUtility.ToJson(plan.sea) != JsonUtility.ToJson(baseline.sea) || JsonUtility.ToJson(plan.light) != JsonUtility.ToJson(baseline.light))
                        throw new Exception("Appearance changed weather");
                    for (int i = 0; i < copy.classes.Length; i++)
                        copy.classes[i].prefabVariants = lists[i];
                }

                foreach (var key in new[]
                {
                    "drone_amvlab",
                    "helicopter_utility_gb",
                    "seagull_dayvable"
                }

                )
                {
                    var p = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/" + key + ".prefab");
                    var animation = p.GetComponent<DatasetMeshAnimation>();
                    var clip = animation.clip;
                    if (clip.frames.Length < 20 || clip.durationSeconds <= 0 || clip.frames.Any(f => f.parts.Length != animation.targets.Length))
                        throw new Exception("Invalid mesh animation");
                    var first = clip.frames[0].parts[0].vertices;
                    var next = clip.frames[clip.frames.Length / 4].parts[0].vertices;
                    if (first.Zip(next, (a, b) => (a - b).sqrMagnitude).Max() < 1e-7f)
                        throw new Exception("Static animation: " + key);
                }
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(copy);
            }

            Debug.Log("[Open Objects] PASS 100 seeds: appearances preserve trajectory/weather/IDs; three mesh animations use actual opaque render geometry.");
        }
    }
}
