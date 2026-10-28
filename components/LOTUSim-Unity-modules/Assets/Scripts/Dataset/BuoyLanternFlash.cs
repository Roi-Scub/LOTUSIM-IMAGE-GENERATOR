using System;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace Lotusim.Dataset
{
    /// <summary>Visual flash cadence only; does not assert an IALA navigation-light specification.</summary>
    public sealed class BuoyLanternFlash : MonoBehaviour
    {
        int m_emissiveColor;
        MaterialPropertyBlock m_previous, m_block;
        MeshRenderer m_lens;
        Camera m_camera;
        DatasetLanternSettings m_settings;
        GameObject m_lightObject;
        Light m_light;
        HDAdditionalLightData m_hdLight;
        Color m_peakEmission;
        float m_startedTime;
        bool m_configured;
        public float Level
        {
            get; private set;
        }
        public float PhaseSeconds
        {
            get; private set;
        }
        public int SampleUnityFrame { get; private set; } = -1;
        public float LastUpdatedRealtime
        {
            get; private set;
        }
        public float AppliedLightLumens => m_settings == null ? 0 : m_settings.pointLightLumens * Level;

        void Awake()
        {
            EnsurePropertyBlocks();
        }

        void EnsurePropertyBlocks()
        {
            // These allocate native Unity objects and cannot run in a
            // MonoBehaviour constructor or serialized field initializer.
            if (m_previous == null)
                m_previous = new MaterialPropertyBlock();
            if (m_block == null)
                m_block = new MaterialPropertyBlock();
        }

        public void Configure(Transform visual, Camera camera, DatasetLanternSettings settings)
        {
            if (visual == null || camera == null || settings == null)
                throw new ArgumentException("Lantern requires the buoy visual, camera and settings.");
            if (m_configured)
                throw new InvalidOperationException("Lantern already configured.");
            settings.Validate();
            // Also supports configuring an inactive object before Awake runs.
            EnsurePropertyBlocks();
            m_emissiveColor = Shader.PropertyToID("_EmissiveColor");
            foreach (var renderer in visual.GetComponentsInChildren<MeshRenderer>())
                if (renderer.name == "AmberFresnelLens")
                {
                    m_lens = renderer;
                    break;
                }

            if (m_lens == null || m_lens.sharedMaterial == null || !m_lens.sharedMaterial.HasProperty(m_emissiveColor))
                throw new InvalidOperationException("The realistic buoy's emissive AmberFresnelLens renderer is missing.");
            m_camera = camera;
            m_settings = settings;
            m_peakEmission = settings.color.linear * settings.peakEmissionIntensity;
            m_lens.GetPropertyBlock(m_previous);
            m_lightObject = new GameObject("Dataset buoy lantern light");
            m_lightObject.transform.SetParent(visual, false);
            m_lightObject.transform.position = m_lens.bounds.center;
            m_light = m_lightObject.AddComponent<Light>();
            m_light.type = LightType.Point;
            m_light.color = settings.color;
            m_light.range = settings.pointLightRangeM;
            m_light.shadows = LightShadows.None;
            m_light.enabled = false;
            m_hdLight = m_lightObject.AddComponent<HDAdditionalLightData>();
            m_hdLight.SetIntensity(0, LightUnit.Lumen);
            m_startedTime = Time.time;
            m_configured = true;
            LastUpdatedRealtime = Time.realtimeSinceStartup;
        }

        void OnEnable()
        {
            RenderPipelineManager.beginCameraRendering += BeforeCamera;
        }

        void BeforeCamera(ScriptableRenderContext context, Camera camera)
        {
            if (!m_configured || camera != m_camera || m_lens == null || SampleUnityFrame == Time.frameCount)
                return;
            SampleUnityFrame = Time.frameCount;
            float elapsed = Time.time - m_startedTime;
            PhaseSeconds = Mathf.Repeat(elapsed + m_settings.phaseOffsetSeconds, m_settings.periodSeconds);
            Level = m_settings.enabled ? EvaluateLevel(elapsed, m_settings) : 0;
            // Per-instance block: never recolor the float or mutate a shared prefab material.
            m_lens.GetPropertyBlock(m_block);
            m_block.SetColor(m_emissiveColor, m_peakEmission * Level);
            m_lens.SetPropertyBlock(m_block);
            m_hdLight.SetIntensity(AppliedLightLumens, LightUnit.Lumen);
            m_light.enabled = Level > 0;
            LastUpdatedRealtime = Time.realtimeSinceStartup;
        }

        void OnDisable()
        {
            RenderPipelineManager.beginCameraRendering -= BeforeCamera;
            if (m_configured && m_lens != null)
                m_lens.SetPropertyBlock(m_previous);
            if (m_light != null)
                m_light.enabled = false;
            if (m_lightObject != null)
                Destroy(m_lightObject);
            m_configured = false;
        }

        public static float EvaluateLevel(float elapsed, DatasetLanternSettings settings)
        {
            if (!settings.enabled)
                return 0;
            float phase = Mathf.Repeat(elapsed + settings.phaseOffsetSeconds, settings.periodSeconds);
            if (phase >= settings.flashSeconds)
                return 0;
            if (settings.edgeFadeSeconds <= 0)
                return 1;
            return Mathf.Clamp01(Mathf.Min(phase, settings.flashSeconds - phase) / settings.edgeFadeSeconds);
        }
    }
}
