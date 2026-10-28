using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering.HighDefinition;

namespace Lotusim.Dataset
{
    [Serializable] public sealed class DatasetAircraftLightState {public string role;public Color color;public float level,emissionMultiplier;}
    // Visual settings only. No certified angular coverage, photometry or flash standard.
    public sealed class DatasetAircraftLights : MonoBehaviour
    {
        sealed class Lens {public MeshRenderer renderer;public MaterialPropertyBlock prior,block;public Color color;public string role;public bool flash;}
        readonly List<Lens> lenses=new List<Lens>();
        readonly List<Material> ownedMaterials=new List<Material>();
        readonly List<GameObject> ownedObjects=new List<GameObject>();
        int emission;
        float phase;
        public DatasetAircraftLightState[] State {get;private set;}=Array.Empty<DatasetAircraftLightState>();
        public void Configure(string category,float phaseSeconds)
        {
            emission=Shader.PropertyToID("_EmissiveColor");phase=phaseSeconds;
            var visual=transform.Find("AerialModel_v1")??transform.Find("FastDroneBankVisual/AerialModel_v1");if(visual==null) throw new InvalidOperationException("Aerial visual marker missing for "+category);
            foreach(var r in visual.GetComponentsInChildren<MeshRenderer>(true)) {
                if(r.name=="NavRed") Add(r,"red_position",new Color(1,.015f,.01f),false);
                if(r.name=="NavGreen") Add(r,"green_position",new Color(.01f,1,.03f),false);
            }
            if(lenses.Count<2) throw new InvalidOperationException("Aircraft red/green navigation-light renderers missing.");
            bool drone=category=="drone";
            Vector3 tail=drone?new Vector3(0,.01f,-.12f):category=="airplane"?new Vector3(0,.32f,-3.55f):new Vector3(0,.59f,-5.06f);
            Vector3 beacon=drone?new Vector3(0,.046f,0):category=="airplane"?new Vector3(0,1.57f,-3.14f):new Vector3(0,1.12f,-.75f);
            Add(Pod(visual,"Sequence white tail diode",tail,drone?.0035f:.025f),"white_tail",Color.white,false);
            Add(Pod(visual,"Sequence red beacon",beacon,drone?.004f:.035f),"red_beacon",new Color(1,.01f,.01f),true);
            State=new DatasetAircraftLightState[lenses.Count];for(int i=0;i<State.Length;i++) State[i]=new DatasetAircraftLightState{role=lenses[i].role,color=lenses[i].color};
        }
        MeshRenderer Pod(Transform parent,string name,Vector3 location,float radius)
        {
            var go=GameObject.CreatePrimitive(PrimitiveType.Sphere);go.name=name;go.transform.SetParent(parent,false);go.transform.localPosition=location;go.transform.localScale=Vector3.one*radius*2;
            Destroy(go.GetComponent<Collider>());var material=new Material(Shader.Find("HDRP/Lit"));material.SetColor("_BaseColor",new Color(.12f,.12f,.12f));
            material.SetFloat("_SurfaceType",0);material.SetFloat("_Metallic",.1f);material.SetFloat("_Smoothness",.8f);HDMaterial.ValidateMaterial(material);
            go.GetComponent<MeshRenderer>().sharedMaterial=material;ownedMaterials.Add(material);ownedObjects.Add(go);return go.GetComponent<MeshRenderer>();
        }
        void Add(MeshRenderer renderer,string role,Color color,bool flash)
        {
            var prior=new MaterialPropertyBlock();renderer.GetPropertyBlock(prior);
            lenses.Add(new Lens{renderer=renderer,prior=prior,block=new MaterialPropertyBlock(),color=color,role=role,flash=flash});
        }
        public static float BeaconLevel(float time,float phase) {float t=Mathf.Repeat(time+phase,1.2f);return t<.12f?Mathf.Clamp01(Mathf.Min(t,.12f-t)/.02f):0;}
        public void Apply(float time)
        {
            for(int i=0;i<lenses.Count;i++) {
                var lens=lenses[i];float level=lens.flash?BeaconLevel(time,phase):1,multiplier=lens.flash?700:300;
                lens.renderer.GetPropertyBlock(lens.block);lens.block.SetColor(emission,lens.color.linear*(multiplier*level));lens.renderer.SetPropertyBlock(lens.block);
                State[i].level=level;State[i].emissionMultiplier=multiplier*level;
            }
        }
        void OnDisable() {foreach(var lens in lenses) if(lens.renderer!=null) lens.renderer.SetPropertyBlock(lens.prior);}
        void OnDestroy() {foreach(var go in ownedObjects) if(go!=null) Destroy(go);foreach(var material in ownedMaterials) if(material!=null) Destroy(material);}
    }
}
