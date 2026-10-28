using System;
using System.IO;
using System.Reflection;
using Lotusim.Dataset;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using Object=UnityEngine.Object;

namespace Lotusim.EditorTools
{
    public static class DatasetLanternLifecycleTests
    {
        const string BatchKey="LOTUSim.LanternNativeTestRequested";

        [MenuItem("LOTUSim/Dataset/Validate lantern Unity lifecycle (in Play)")]
        public static void Run()
        {
            if(!Application.isPlaying) throw new InvalidOperationException("Run this native lifecycle test in Play, e.g. in the wave preview scene.");
            Check();Debug.Log("[Dataset] Native lantern lifecycle PASS: active/inactive AddComponent, configuration, flash, source-material preservation and cleanup.");
        }

        public static void Check()
        {
            if(!Application.isPlaying) throw new InvalidOperationException("Unity Play mode is required for native lifecycle checks.");
            CheckFixture(true,true);CheckFixture(false,true);CheckFixture(true,false);
        }

        static void CheckFixture(bool initiallyActive,bool enabled)
        {
            var root=new GameObject("Dataset lantern native test");
            var cameraObject=new GameObject("Dataset lantern test camera");
            Material material=null;
            try {
                root.hideFlags=HideFlags.DontSave;cameraObject.hideFlags=HideFlags.DontSave;
                root.transform.position=new Vector3(3,4,5);root.transform.rotation=Quaternion.Euler(0,38,0);
                var visual=new GameObject("MarineBuoyVisual_v1");visual.transform.SetParent(root.transform,false);
                var lens=GameObject.CreatePrimitive(PrimitiveType.Cube);lens.name="AmberFresnelLens";
                lens.transform.SetParent(visual.transform,false);
                var renderer=lens.GetComponent<MeshRenderer>();
                var shader=Shader.Find("HDRP/Lit");Assert(shader!=null,"HDRP shader available");
                material=new Material(shader);renderer.sharedMaterial=material;
                int emission=Shader.PropertyToID("_EmissiveColor"),sentinel=Shader.PropertyToID("_DatasetTestSentinel");
                Color original=new Color(.2f,.1f,.02f),previous=new Color(2,3,4);
                material.SetColor(emission,original);
                var block=new MaterialPropertyBlock();block.SetColor(emission,previous);block.SetFloat(sentinel,17);renderer.SetPropertyBlock(block);
                var camera=cameraObject.AddComponent<Camera>();camera.enabled=false;
                root.SetActive(initiallyActive);
                // The regression requires real AddComponent in Unity: a pure
                // C# compiler/cadence test cannot catch native constructor errors.
                var flash=root.AddComponent<BuoyLanternFlash>();
                flash.Configure(visual.transform,camera,new DatasetLanternSettings{enabled=enabled,phaseOffsetSeconds=.1f});
                if(!initiallyActive) root.SetActive(true);
                typeof(BuoyLanternFlash).GetMethod("BeforeCamera",BindingFlags.NonPublic|BindingFlags.Instance)
                    .Invoke(flash,new object[]{default(ScriptableRenderContext),camera});
                Assert(flash.SampleUnityFrame==Time.frameCount,"Flash updated in this Unity frame");
                Assert(enabled?flash.Level>.99f:flash.Level==0,"Correct light on/off state");
                renderer.GetPropertyBlock(block);
                Assert(block.GetFloat(sentinel)==17,"Unrelated material override preserved");
                Assert(enabled?block.GetColor(emission).r>100:block.GetColor(emission).r==0,"Emission override applied");
                Assert(material.GetColor(emission)==original,"Shared material not mutated");
                Assert(root.transform.position==new Vector3(3,4,5),"Root position not mutated");
                Assert(Quaternion.Angle(root.transform.rotation,Quaternion.Euler(0,38,0))<.001f,"Root rotation not mutated");
                var light=visual.GetComponentInChildren<Light>(true);
                Assert(light!=null&&light.enabled==enabled,"Point light configured");
                flash.enabled=false;
                renderer.GetPropertyBlock(block);
                Assert(block.GetColor(emission)==previous&&block.GetFloat(sentinel)==17,"Property block restored on disable");
                Assert(!light.enabled,"Point light disabled on cleanup");
            }
            finally {
                Object.DestroyImmediate(root);Object.DestroyImmediate(cameraObject);
                if(material!=null) Object.DestroyImmediate(material);
            }
        }
        static void Assert(bool ok,string label) {if(!ok) throw new InvalidOperationException("Native lantern test failed: "+label);}

        public static void RunInBatch()
        {
            if(!Application.isBatchMode) throw new InvalidOperationException("RunInBatch is for an isolated batch Unity project only.");
            SessionState.SetBool(BatchKey,true);EditorApplication.EnterPlaymode();
        }

        [InitializeOnLoadMethod]
        static void RegisterBatchContinuation()
        {
            EditorApplication.playModeStateChanged+=state=>{
                if(state==PlayModeStateChange.EnteredPlayMode&&Application.isBatchMode&&SessionState.GetBool(BatchKey,false))
                    EditorApplication.delayCall+=FinishBatch;
            };
        }
        static void FinishBatch()
        {
            SessionState.SetBool(BatchKey,false);
            try {
                Check();
                File.WriteAllText(Path.Combine(Application.dataPath,"..","lantern-native-result.json"),"{\"passed\":true,\"fixtures\":3,\"unity\":\""+Application.unityVersion+"\",\"test\":\"real_play_mode_lantern_lifecycle\"}");
                Debug.Log("[Dataset Native Lantern] PASS: 3 Play-mode lifecycle fixtures.");EditorApplication.Exit(0);
            }
            catch(Exception exception) {
                Debug.LogError("[Dataset Native Lantern] FAIL: "+exception);EditorApplication.Exit(1);
            }
        }
    }
}
