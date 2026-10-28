using System;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace Lotusim.Dataset
{
    // Inspection only: no ROS connection. Free hydrostatic mode is marine-only;
    // aircraft deliberately remain kinematic (no claimed aerodynamic solver).
    public sealed class DatasetAssetShowcase : MonoBehaviour
    {
        public GameObject[] prefabs;
        public Camera viewCamera;
        public WaterSurface ocean;
        public Light sun;
        public Volume environment;
        public HDRenderPipelineAsset waterPipeline;
        public int selected;
        public float azimuth = 48, elevation = 23, zoom = 1, windKmh = 45;
        public bool freeBoatPhysics, night;
        GameObject current;
        Bounds bounds;
        RenderPipelineAsset prior;
        MarineVesselWaveMotion marine;
        void Start()
        {
            prior = QualitySettings.renderPipeline;
            QualitySettings.renderPipeline = waterPipeline;
            ocean.cpuSimulation = true;
            ocean.cpuFullResolution = true;
            ocean.largeChaos = .6f;
            ocean.repetitionSize = 256;
            ocean.absorptionDistance = .8f;
            ocean.maxRefractionDistance = .6f;
            ocean.refractionColor = new Color(.06f, .24f, .30f);
            ocean.scatteringColor = new Color(.03f, .16f, .19f);
            var p = environment.profile;
            Set<VisualEnvironment>(p).skyType.Override((int)SkyType.PhysicallyBased);
            Set<VisualEnvironment>(p).skyAmbientMode.Override(SkyAmbientMode.Dynamic);
            Set<PhysicallyBasedSky>(p).updateMode.Override(EnvironmentUpdateMode.Realtime);
            Set<PhysicallyBasedSky>(p).updatePeriod.Override(0);
            Set<Exposure>(p).mode.Override(ExposureMode.Fixed);
            Set<Exposure>(p).compensation.Override(0);
            Set<WaterRendering>(p).enable.Override(true);
            Set<MotionBlur>(p).intensity.Override(0);
            Set<DepthOfField>(p).focusMode.Override(DepthOfFieldMode.Off);
            sun.type = LightType.Directional;
            sun.transform.rotation = Quaternion.LookRotation(new Vector3(-.55f, -1, -.4f));
            if (sun.GetComponent<HDAdditionalLightData>() == null)
                sun.gameObject.AddComponent<HDAdditionalLightData>();
            RenderSettings.sun = sun;
            viewCamera.fieldOfView = 35;
            viewCamera.farClipPlane = 10000;
            Spawn();
        }

        static T Set<T>(VolumeProfile p)
            where T : VolumeComponent
        {
            if (!p.TryGet<T>(out var c))
                c = p.Add<T>();
            c.active = true;
            return c;
        }

        public void Spawn()
        {
            if (current != null)
            {
                current.SetActive(false);
                Destroy(current);
            }

            selected = Mathf.Clamp(selected, 0, prefabs.Length - 1);
            current = Instantiate(prefabs[selected]);
            current.name = prefabs[selected].name;
            marine = current.GetComponent<MarineVesselWaveMotion>();
            if (marine != null)
            {
                marine.mode = freeBoatPhysics ? MarineWaveMode.FreeRigidbody : MarineWaveMode.VisualResponse;
                marine.Configure(ocean, viewCamera, false);
            }

            var buoy = current.transform.Find(BuoyWaveMotion.VisualChildName);
            if (buoy != null)
            {
                current.AddComponent<BuoyWaveMotion>().Configure(ocean, buoy, viewCamera, new DatasetFlotationSettings());
                current.AddComponent<BuoyLanternFlash>().Configure(buoy, viewCamera, new DatasetLanternSettings());
            }

            if (current.GetComponent<DatasetAerialResponse>() != null)
                current.transform.position = Vector3.up * 20;
            var renderers = current.GetComponentsInChildren<MeshRenderer>();
            bounds = renderers[0].bounds;
            for (int i = 1; i < renderers.Length; i++)
                bounds.Encapsulate(renderers[i].bounds);
            bounds.center -= current.transform.position;
            HDCamera.GetOrCreate(viewCamera).Reset();
        }

        void LateUpdate()
        {
            if (current == null)
                return;
            ocean.largeWindSpeed = windKmh;
            ocean.largeBand0Multiplier = Mathf.Clamp01(windKmh / 45);
            ocean.largeBand1Multiplier = Mathf.Clamp01(windKmh / 65);
            ocean.ripples = true;
            ocean.ripplesWindSpeed = windKmh * .22f;
            sun.GetComponent<HDAdditionalLightData>().SetIntensity(night ? .3f : 80000, LightUnit.Lux);
            Set<Exposure>(environment.profile).fixedExposure.Override(night ? -4 : 11.8f);
            float distance = bounds.extents.magnitude / Mathf.Sin(viewCamera.fieldOfView * Mathf.Deg2Rad / 2) * zoom;
            var center = current.transform.TransformPoint(bounds.center);
            viewCamera.transform.position = center + DatasetCampaignConfig.OrbitOffset(distance, azimuth, elevation);
            viewCamera.transform.LookAt(center);
            viewCamera.nearClipPlane = Mathf.Max(.015f, distance * .001f);
        }

        void OnGUI()
        {
            GUILayout.BeginArea(new Rect(12, 12, 330, 530), GUI.skin.box);
            GUILayout.Label("Objets libres — aperçu hors ROS");
            for (int i = 0; i < prefabs.Length; i++)
                if (GUILayout.Button((selected == i ? "● " : "") + DatasetExternalAssetCatalog.Names[i]))
                {
                    selected = i;
                    Spawn();
                }

            GUILayout.Label("Angle / élévation / distance");
            azimuth = GUILayout.HorizontalSlider(azimuth, -180, 180);
            elevation = GUILayout.HorizontalSlider(elevation, -5, 65);
            zoom = GUILayout.HorizontalSlider(zoom, .55f, 2);
            GUILayout.Label("Vent : " + windKmh.ToString("F0") + " km/h");
            windKmh = GUILayout.HorizontalSlider(windKmh, 0, 80);
            night = GUILayout.Toggle(night, "Nuit / vérifier les feux");
            if (marine != null)
            {
                bool next = GUILayout.Toggle(freeBoatPhysics, "Flottabilité Rigidbody libre (approximation)");
                if (next != freeBoatPhysics)
                {
                    freeBoatPhysics = next;
                    Spawn();
                }
            }
            else
                GUILayout.Label("Racine cinématique ; houle ou animations visuelles.\nPas de simulation aérodynamique validée.");
            GUILayout.EndArea();
        }

        void OnDisable()
        {
            if (current != null)
                Destroy(current);
            QualitySettings.renderPipeline = prior;
        }
    }
}
