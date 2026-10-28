using System;
using UnityEngine;
using UnityEngine.Rendering.HighDefinition;
namespace Lotusim.Dataset
{
    [Serializable] public sealed class DatasetAssetLight
    {
        public string role;
        public MeshRenderer lens;
        public Light point;
        public Color color=Color.white;
        public float peakEmission=8,lumens=1,periodSeconds,flashSeconds;
    }
    // Authored anchors in metres (+X nose, +Z port), not a certified COLREG/
    // aviation photometric model. Moderate point lights and emissive lenses.
    public sealed class DatasetAssetLights : MonoBehaviour
    {
        public DatasetAssetLight[] lamps=Array.Empty<DatasetAssetLight>();
        [NonSerialized] public bool externalClock;
        MaterialPropertyBlock block;
        DatasetAircraftLightState[] state;
        public DatasetAircraftLightState[] State=>state??Array.Empty<DatasetAircraftLightState>();
        public void Apply(float seconds,float phase=0)
        {
            if(block==null)block=new MaterialPropertyBlock();
            if(state==null||state.Length!=lamps.Length)state=new DatasetAircraftLightState[lamps.Length];
            for(int i=0;i<lamps.Length;i++) {
                var lamp=lamps[i];float level=lamp.periodSeconds<=0||Mathf.Repeat(seconds+phase,lamp.periodSeconds)<lamp.flashSeconds?1:0;
                lamp.lens.GetPropertyBlock(block);block.SetColor("_EmissiveColor",lamp.color.linear*(lamp.peakEmission*level));lamp.lens.SetPropertyBlock(block);
                if(lamp.point!=null){lamp.point.enabled=level>0;lamp.point.GetComponent<HDAdditionalLightData>()?.SetIntensity(lamp.lumens*level,LightUnit.Lumen);}
                state[i]=new DatasetAircraftLightState{role=lamp.role,color=lamp.color,level=level,emissionMultiplier=lamp.peakEmission};
            }
        }
        void LateUpdate(){if(!externalClock)Apply(Time.time);}
        void OnDisable(){foreach(var lamp in lamps)if(lamp.point!=null)lamp.point.enabled=false;}
    }
}
