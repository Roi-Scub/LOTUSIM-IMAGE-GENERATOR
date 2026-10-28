using System;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace Lotusim.Dataset
{
    // A standalone inspection scene. Deliberately no ROS connection or dataset
    // runner: free Rigidbody mode is safe to explore here without two writers.
    public sealed class MarineLibraryShowcase : MonoBehaviour
    {
        public GameObject[] prefabs;
        public string[] displayNames;
        public Camera viewCamera;
        public WaterSurface ocean;
        public Light sun;
        public Volume environment;
        public HDRenderPipelineAsset waterPipeline;
        public float azimuthDeg=48,elevationDeg=23,zoom=1,windKmh=45;
        public int selected;
        public bool freePhysics;
        GameObject current;
        MarineVesselWaveMotion response;
        Bounds localBounds;
        RenderPipelineAsset previousPipeline;
        bool changedPipeline;
        void Start()
        {
            if(prefabs==null||prefabs.Length==0||viewCamera==null||ocean==null||sun==null||environment==null||waterPipeline==null) throw new InvalidOperationException("Marine showcase references missing.");
            previousPipeline=QualitySettings.renderPipeline;QualitySettings.renderPipeline=waterPipeline;changedPipeline=true;
            ocean.cpuSimulation=true;ocean.cpuFullResolution=true;ocean.largeChaos=.6f;ocean.repetitionSize=256;
            ocean.absorptionDistance=.8f;ocean.maxRefractionDistance=.6f;ocean.refractionColor=new Color(.06f,.24f,.30f);ocean.scatteringColor=new Color(.03f,.16f,.19f);
            var profile=environment.profile;Set<VisualEnvironment>(profile).skyType.Override((int)SkyType.PhysicallyBased);Set<VisualEnvironment>(profile).skyAmbientMode.Override(SkyAmbientMode.Dynamic);
            Set<PhysicallyBasedSky>(profile).updateMode.Override(EnvironmentUpdateMode.Realtime);Set<PhysicallyBasedSky>(profile).updatePeriod.Override(0);
            Set<Exposure>(profile).mode.Override(ExposureMode.Fixed);Set<Exposure>(profile).fixedExposure.Override(11.8f);Set<Exposure>(profile).compensation.Override(0);Set<WaterRendering>(profile).enable.Override(true);
            Set<MotionBlur>(profile).intensity.Override(0);Set<DepthOfField>(profile).focusMode.Override(DepthOfFieldMode.Off);
            sun.type=LightType.Directional;sun.transform.rotation=Quaternion.LookRotation(new Vector3(-.55f,-1,-.4f));
            var hd=sun.GetComponent<HDAdditionalLightData>();if(hd==null) hd=sun.gameObject.AddComponent<HDAdditionalLightData>();hd.SetIntensity(80000,LightUnit.Lux);RenderSettings.sun=sun;
            viewCamera.fieldOfView=35;viewCamera.farClipPlane=10000;
            var data=viewCamera.GetComponent<HDAdditionalCameraData>();if(data==null) data=viewCamera.gameObject.AddComponent<HDAdditionalCameraData>();data.clearColorMode=HDAdditionalCameraData.ClearColorMode.Sky;
            Spawn();
        }
        static T Set<T>(VolumeProfile profile) where T:VolumeComponent {if(!profile.TryGet<T>(out var value)) value=profile.Add<T>();value.active=true;return value;}
        public void Spawn()
        {
            if(current!=null) {current.SetActive(false);Destroy(current);}
            selected=Mathf.Clamp(selected,0,prefabs.Length-1);current=Instantiate(prefabs[selected]);current.name=prefabs[selected].name;
            response=current.GetComponent<MarineVesselWaveMotion>();response.mode=freePhysics?MarineWaveMode.FreeRigidbody:MarineWaveMode.VisualResponse;response.Configure(ocean,viewCamera,false);
            var renderers=current.GetComponentsInChildren<MeshRenderer>();localBounds=renderers[0].bounds;for(int i=1;i<renderers.Length;i++) localBounds.Encapsulate(renderers[i].bounds);
            HDCamera.GetOrCreate(viewCamera).Reset();
        }
        void LateUpdate()
        {
            if(current==null) return;
            float wind=Mathf.Clamp(windKmh,0,80);ocean.largeWindSpeed=wind;ocean.largeBand0Multiplier=Mathf.Clamp01(wind/45);ocean.largeBand1Multiplier=Mathf.Clamp01(wind/65);
            ocean.ripples=true;ocean.ripplesWindSpeed=wind*.22f;
            float distance=localBounds.extents.magnitude/Mathf.Sin(viewCamera.fieldOfView*Mathf.Deg2Rad/2)*Mathf.Clamp(zoom,.5f,2);
            var target=current.transform.TransformPoint(localBounds.center);
            viewCamera.transform.position=target+DatasetCampaignConfig.OrbitOffset(distance,azimuthDeg,elevationDeg);viewCamera.transform.LookAt(target);viewCamera.nearClipPlane=Mathf.Max(.03f,distance*.001f);
        }
        void OnGUI()
        {
            GUILayout.BeginArea(new Rect(12,12,310,455),GUI.skin.box);
            GUILayout.Label("Bibliothèque marine — aperçu hors ROS");
            for(int i=0;i<prefabs.Length;i++) if(GUILayout.Button((selected==i?"● ":"")+(displayNames!=null&&i<displayNames.Length?displayNames[i]:i<MarineVesselCatalog.DisplayNames.Length?MarineVesselCatalog.DisplayNames[i]:prefabs[i].name))) {selected=i;Spawn();}
            GUILayout.Label("Angle de vue");azimuthDeg=GUILayout.HorizontalSlider(azimuthDeg,-180,180);
            GUILayout.Label("Hauteur de vue");elevationDeg=GUILayout.HorizontalSlider(elevationDeg,5,65);
            GUILayout.Label("Distance / zoom");zoom=GUILayout.HorizontalSlider(zoom,.5f,2);
            GUILayout.Label("Vent : "+windKmh.ToString("F0")+" km/h");windKmh=GUILayout.HorizontalSlider(windKmh,0,80);
            bool next=GUILayout.Toggle(freePhysics,"Physique Unity libre (approximation)");if(next!=freePhysics) {freePhysics=next;Spawn();}
            if(response!=null) GUILayout.Label(response.HasValidSample?"Houle active · "+(freePhysics?"Rigidbody":"racine fixe / visuel flottant"):response.LastQueryFailure);
            GUILayout.EndArea();
        }
        void OnDisable()
        {
            if(current!=null) Destroy(current);if(changedPipeline) {QualitySettings.renderPipeline=previousPipeline;changedPipeline=false;}
        }
    }
}
