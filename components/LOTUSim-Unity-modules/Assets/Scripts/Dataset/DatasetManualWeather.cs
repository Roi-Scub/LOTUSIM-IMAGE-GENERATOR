using System;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace Lotusim.Dataset
{
    // Explicit visual proxies, not measured cloud oktas / rain mm per hour.
    // Never edits the shared VolumeProfile or HDRP pipeline asset.
    public sealed class DatasetManualWeather : MonoBehaviour
    {
        Texture2D cloudMap;
        Material rainMaterial;
        GameObject rain;
        public void Configure(VolumeProfile profile,Camera camera,DatasetManualEnvironment environment,int seed)
        {
            environment.Validate();
            var visual=Override<VisualEnvironment>(profile);visual.cloudType.Override((int)CloudType.CloudLayer);
            var clouds=Override<CloudLayer>(profile);clouds.opacity.Override(environment.cloudCover>0?1:0);
            clouds.upperHemisphereOnly.Override(true);clouds.layerA.altitude.Override(1800);
            cloudMap=new Texture2D(256,128,TextureFormat.RGBA32,false,true){name="Manual campaign procedural cloud proxy",wrapMode=TextureWrapMode.Repeat};
            var pixels=new Color32[256*128];float phase=(seed&65535)*.013f;
            for(int y=0;y<128;y++)for(int x=0;x<256;x++) {
                float n=.65f*Mathf.PerlinNoise(x*.025f+phase,y*.045f)+.35f*Mathf.PerlinNoise(x*.073f+phase,y*.12f);
                float value=environment.cloudCover<=0?0:Mathf.SmoothStep(0,1,(n-(1-environment.cloudCover))/.18f+.5f);
                byte v=(byte)(value*255);pixels[y*256+x]=new Color32(v,v,v,255);
            }
            cloudMap.SetPixels32(pixels);cloudMap.Apply(false,false);clouds.layerA.cloudMap.Override(cloudMap);
            clouds.layerA.opacityR.Override(1);clouds.layerA.opacityG.Override(0);clouds.layerA.opacityB.Override(0);clouds.layerA.opacityA.Override(0);
            var fog=Override<Fog>(profile);fog.enabled.Override(environment.rainIntensity>0);
            fog.meanFreePath.Override(Mathf.Lerp(5000,450,environment.rainIntensity));fog.maximumHeight.Override(250);
            if(environment.rainIntensity<=0)return;
            var shader=Shader.Find("HDRP/Unlit");if(shader==null)throw new InvalidOperationException("HDRP/Unlit required for manual visual rain.");
            rainMaterial=new Material(shader){name="Manual campaign visual rain"};
            rainMaterial.SetColor("_UnlitColor",new Color(.48f,.58f,.65f,.17f));
            HDMaterial.SetSurfaceType(rainMaterial,true);HDMaterial.ValidateMaterial(rainMaterial);
            rain=new GameObject("Visual rain proxy — not calibrated precipitation");rain.transform.SetParent(camera.transform,false);rain.transform.localPosition=new Vector3(0,8,9);
            var particles=rain.AddComponent<ParticleSystem>();particles.Stop(true,ParticleSystemStopBehavior.StopEmittingAndClear);
            var main=particles.main;main.playOnAwake=false;main.loop=true;main.useUnscaledTime=false;main.duration=3;
            main.startLifetime=1.1f;main.startSpeed=0;main.startSize=.022f;main.startColor=new Color(.7f,.8f,.9f,.35f);
            main.maxParticles=3000;main.simulationSpace=ParticleSystemSimulationSpace.World;
            particles.useAutoRandomSeed=false;particles.randomSeed=unchecked((uint)seed)+1;
            var emission=particles.emission;emission.rateOverTime=environment.rainIntensity*1600;
            var shape=particles.shape;shape.shapeType=ParticleSystemShapeType.Box;shape.scale=new Vector3(35,1,30);
            var velocity=particles.velocityOverLifetime;velocity.enabled=true;velocity.space=ParticleSystemSimulationSpace.World;
            var wind=DatasetSequenceConfig.Bearing(environment.waveDirectionDeg)*environment.windMps*.2f;
            velocity.x=wind.x;velocity.y=-16;velocity.z=wind.z;
            var renderer=particles.GetComponent<ParticleSystemRenderer>();renderer.sharedMaterial=rainMaterial;
            renderer.renderMode=ParticleSystemRenderMode.Stretch;renderer.lengthScale=5;renderer.velocityScale=.02f;
            renderer.shadowCastingMode=ShadowCastingMode.Off;renderer.receiveShadows=false;particles.Play();
        }
        static T Override<T>(VolumeProfile p) where T:VolumeComponent {if(!p.TryGet<T>(out var value))value=p.Add<T>();value.active=true;return value;}
        void OnDisable() {if(rain!=null)rain.SetActive(false);}
        void OnDestroy() {if(rain!=null)Destroy(rain);if(rainMaterial!=null)Destroy(rainMaterial);if(cloudMap!=null)Destroy(cloudMap);}
    }
}
