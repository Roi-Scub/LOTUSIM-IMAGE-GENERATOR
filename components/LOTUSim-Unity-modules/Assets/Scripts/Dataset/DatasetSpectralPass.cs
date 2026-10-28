using System;
using UnityEngine;
using UnityEngine.Experimental.Rendering;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace Lotusim.Dataset
{
    // Co-registered appearance proxies, not a calibrated LWIR or intensifier
    // sensor. No alternate camera, transform, connection or random geometry.
    [Serializable]
    public sealed class DatasetSpectralPass : CustomPass
    {
        [NonSerialized]
        public Camera camera;
        [NonSerialized]
        public DatasetSensorSettings settings;
        [NonSerialized]
        public DatasetSequenceActor[] actors = Array.Empty<DatasetSequenceActor>();
        [NonSerialized]
        public MeshRenderer[] observer = Array.Empty<MeshRenderer>();
        [NonSerialized]
        public int width, height, seed, sourceFrame;
        [NonSerialized]
        public bool armed;
        public int Frame { get; private set; } = -1;
        public string Error
        {
            get; private set;
        }
        public RTHandle Thermal
        {
            get; private set;
        }
        public RTHandle NightVision
        {
            get; private set;
        }

        Material material;
        protected override bool executeInSceneView => false;

        protected override void Setup(ScriptableRenderContext context, CommandBuffer cmd)
        {
            var shader = Resources.Load<Shader>("Dataset/SpectralCapture");
            if (shader == null || !shader.isSupported)
            {
                Error = "Synthetic sensor shader unavailable.";
                return;
            }

            material = CoreUtils.CreateEngineMaterial(shader);
            if (settings.thermal)
                Thermal = RTHandles.Alloc(width, height, colorFormat: GraphicsFormat.R8G8B8A8_UNorm, useDynamicScale: false, name: "Dataset synthetic IR");
            if (settings.nightVision)
                NightVision = RTHandles.Alloc(width, height, colorFormat: GraphicsFormat.R8G8B8A8_UNorm, useDynamicScale: false, name: "Dataset night vision");
        }

        protected override void Execute(CustomPassContext ctx)
        {
            if (!armed || ctx.hdCamera.camera != camera || Error != null)
                return;
            try
            {
                if (ctx.hdCamera.actualWidth != width || ctx.hdCamera.actualHeight != height)
                    throw new InvalidOperationException("Sensor capture size differs from RGB.");
                ctx.cmd.SetGlobalTexture("_DatasetSensorDepth", ctx.cameraDepthBuffer);
                ctx.cmd.SetGlobalTexture("_DatasetSensorColor", ctx.cameraColorBuffer);
                ctx.cmd.SetGlobalVector("_DatasetThermalWindow", new Vector4(settings.thermalMinC, settings.thermalMaxC, settings.skyTemperatureC, settings.waterTemperatureC));
                ctx.cmd.SetGlobalFloat("_DatasetBlackHot", settings.blackHot ? 1 : 0);
                if (Thermal != null)
                {
                    CoreUtils.SetRenderTarget(ctx.cmd, Thermal, ctx.cameraDepthBuffer, ClearFlag.Color, Color.black);
                    CoreUtils.DrawFullScreen(ctx.cmd, material, shaderPassId: 0);
                    Draw(ctx, observer, settings.backgroundTemperatureC, .92f);
                    foreach (var actor in actors)
                    {
                        var profile = settings.Profile(actor.definition.category);
                        Draw(ctx, actor.mask.renderers, profile.temperatureC, profile.emissivity);
                    }
                }

                if (NightVision != null)
                {
                    CoreUtils.SetRenderTarget(ctx.cmd, NightVision, ClearFlag.Color, Color.black);
                    ctx.cmd.SetGlobalVector("_DatasetNightParams", new Vector4(settings.nightGain, settings.nightGamma, settings.nightNoise, settings.nightVignette));
                    ctx.cmd.SetGlobalColor("_DatasetNightTint", settings.nightTint);
                    ctx.cmd.SetGlobalFloat("_DatasetSensorNoisePhase", (seed % 65521) + sourceFrame * 17.17f);
                    CoreUtils.DrawFullScreen(ctx.cmd, material, shaderPassId: 2);
                }

                CoreUtils.SetRenderTarget(ctx.cmd, ctx.cameraColorBuffer, ctx.cameraDepthBuffer, ClearFlag.None);
                Frame = Time.frameCount;
                armed = false;
            }
            catch (Exception e)
            {
                Error = e.ToString();
            }
        }

        void Draw(CustomPassContext ctx, MeshRenderer[] renderers, float temperature, float emissivity)
        {
            ctx.cmd.SetGlobalVector("_DatasetSurfaceThermal", new Vector4(temperature, emissivity, settings.skyTemperatureC, settings.waterTemperatureC));
            foreach (var renderer in renderers)
                if (renderer != null && renderer.enabled && renderer.gameObject.activeInHierarchy)
                {
                    var mesh = renderer.GetComponent<MeshFilter>()?.sharedMesh;
                    if (mesh == null)
                        continue;
                    for (int sub = 0; sub < mesh.subMeshCount; sub++)
                        ctx.cmd.DrawRenderer(renderer, material, sub, 1);
                }
        }

        protected override void Cleanup()
        {
            CoreUtils.Destroy(material);
            Thermal?.Release();
            NightVision?.Release();
            Thermal = null;
            NightVision = null;
        }
    }
}
