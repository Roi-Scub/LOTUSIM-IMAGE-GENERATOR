using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace Lotusim.Dataset
{
    [DefaultExecutionOrder(-4500)]
    public sealed class DatasetSequenceRunner : MonoBehaviour
    {
        public DatasetSequenceConfig configuration;
        public Camera captureCamera;
        public WaterSurface ocean;
        public Light sun;
        public Volume environmentVolume;
        public HDRenderPipelineAsset waterPipeline;
        public bool autoStart = true;
        public DatasetLotusimSource lotusimSource;
        public string MotionSource => lotusimSource == null ? "Unity kinematic; no live ROS" : "LOTUSim ENU kinematic timeline";
        public string Status { get; private set; } = "idle";
        public string OutputDirectory
        {
            get; private set;
        }
        public int Captured => exporter == null ? captured : exporter.Count;
        public int Expected => config == null ? 0 : config.ImageCount;
        public int Boxes => exporter == null ? boxes : exporter.Boxes;
        public RenderTexture Preview => target;

        DatasetSequenceConfig config;
        DatasetSequencePlan plan;
        DatasetSequenceActor[] actors, active = Array.Empty<DatasetSequenceActor>();
        DatasetMultiInstanceMaskPass pass;
        DatasetSpectralPass spectral;
        DatasetSequenceExport exporter;
        GameObject passObject;
        RenderTexture target, priorTarget;
        Texture2D pixels;
        RenderPipelineAsset priorPipeline;
        int priorFps, warmup, simulationFrame, preparedFrame = -1, captured, boxes, lastRenderedUnityFrame = -1;
        bool running, settingsChanged, waterValid, finishing;
        GameObject observerRoot;
        MarineVesselWaveMotion observerMotion;
        DatasetVesselCameraMount cameraMount;
        Pose observerPose;
        float lastRender, queryLastValid, pitch, roll, heave;
        Vector3 nominal, waterNormal = Vector3.up;
        Quaternion heading;
        string sequenceId, error = "";
        VolumeProfile profile;
        DatasetLightPreset currentLight;
        DatasetSeaPreset currentSea;
        DatasetManualWeather manualWeather;
        int lightingPhase = -1, lightingWarmup, lightingWarmupFrame = -1;
        [Serializable]
        sealed class StatusRecord
        {
            public string status, error, sequenceId, motionSource = "Unity kinematic; no live ROS";
            public int captured, expected, boxes;
        }

        void Start()
        {
            if (autoStart)
                StartSequence();
        }

        public void ValidateSceneReferences()
        {
            var missing = new List<string>();
            if (configuration == null)
                missing.Add(nameof(configuration));
            if (captureCamera == null)
                missing.Add(nameof(captureCamera));
            if (ocean == null)
                missing.Add(nameof(ocean));
            if (sun == null)
                missing.Add(nameof(sun));
            if (environmentVolume == null)
                missing.Add(nameof(environmentVolume));
            if (waterPipeline == null)
                missing.Add(nameof(waterPipeline));
            if (missing.Count > 0)
                throw new InvalidOperationException("Sequence references missing: " + string.Join(", ", missing) + ". Reopen the dataset scene using its LOTUSim menu before Play.");
            foreach (var component in new Component[]
            {
                captureCamera,
                ocean,
                sun,
                environmentVolume,
                lotusimSource
            }

            )
                if (component != null && component.gameObject.scene != gameObject.scene)
                    throw new InvalidOperationException("Sequence reference '" + component.name + "' belongs to another scene. Reopen the dataset scene using its LOTUSim menu before Play.");
        }

        [ContextMenu("Start randomized sequence")]
        public void StartSequence()
        {
            if (Status != "idle")
                return;
            try
            {
                ValidateSceneReferences();
                config = Instantiate(configuration);
                config.Validate();
                plan = config.MakePlan();
                if (QualitySettings.activeColorSpace != ColorSpace.Linear)
                    throw new InvalidOperationException("HDRP sequence capture requires Linear color space. Change Player Settings > Color Space outside Play.");
                var settings = waterPipeline.currentPlatformRenderPipelineSettings;
                if (!settings.supportWater || !settings.waterCPUSimulation || !settings.supportCustomPass || ocean.waterMask != null)
                    throw new InvalidOperationException("Enable HDRP Water, Script Interactions and Custom Pass; use an unmasked ocean.");
                sequenceId = "seq_" + DateTime.UtcNow.ToString("yyyyMMdd_HHmmss") + "_" + Guid.NewGuid().ToString("N").Substring(0, 8);
                OutputDirectory = Path.GetFullPath(Path.Combine(Application.dataPath, "..", config.outputRoot, sequenceId));
                Directory.CreateDirectory(OutputDirectory);
                DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "requested-config.json"), JsonUtility.ToJson(config, true));
                var archivedPlan = JsonUtility.FromJson<DatasetSequencePlan>(JsonUtility.ToJson(plan));
                archivedPlan.motionSource = MotionSource;
                DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "events.json"), JsonUtility.ToJson(archivedPlan, true));
                DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "provenance.json"), "{\"renderer\":\"Unity HDRP 14\",\"motion_source\":\"" + MotionSource + "\",\"flight_dynamics\":false,\"gazebo_hydrodynamics\":false,\"pixel_replay_guaranteed\":false,\"camera_water_latency\":\"previous completed render\",\"rgb_annotation_same_render\":true,\"gazebo_clock_equals_dataset_clock\":false}");
                if (config.manualPlan != null)
                {
                    DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "manual-campaign.json"), config.manualPlan.campaignJson);
                    DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "manual-image.json"), JsonUtility.ToJson(plan.manual, true));
                }

                if (lotusimSource != null)
                {
                    DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, config.ScenarioName + ".requested.yaml"), DatasetLotusimScenario.Yaml(config, plan));
                    lotusimSource.Begin(config, plan);
                }

                ConfigureRendering();
                CreateActors();
                DatasetBoatVariants.WriteCredits(OutputDirectory, actors);
                if (config.trafficPlan != null)
                {
                    var bundle = config.trafficPlan;
                    DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "traffic-scope.json"), bundle.scopeJson);
                    DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "traffic-catalogue.json"), bundle.catalogueJson);
                    DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "traffic-safety-audit.json"), bundle.auditJson);
                    DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "traffic-agent-messages.json"), bundle.messagesJson);
                }

                if (lotusimSource != null)
                {
                    observerRoot = Instantiate(lotusimSource.observerPrefab);
                    observerRoot.name = DatasetLotusimScenario.Observer;
                    observerRoot.SetActive(false);
                    if (config.observerDeckCamera)
                    {
                        observerMotion = observerRoot.GetComponent<MarineVesselWaveMotion>();
                        if (observerMotion == null)
                            throw new InvalidOperationException("Update the FREMM prefab with Dataset menu 7 before using its deck camera.");
                        observerMotion.angularResponseGain = config.observerWaveTiltGain;
                        observerMotion.parameters.maxRollDeg = config.observerMaxRollDeg;
                        observerMotion.parameters.maxPitchDeg = config.observerMaxPitchDeg;
                        observerMotion.Configure(ocean, captureCamera, true);
                        cameraMount = gameObject.AddComponent<DatasetVesselCameraMount>();
                        cameraMount.Attach(observerMotion, captureCamera, config.observerDeckOffsetM, Quaternion.Euler(0, 90 + config.viewHeadingDeg - config.routeHeadingDeg, 0) * Quaternion.Euler(config.viewDownPitchDeg, 0, 0));
                    }
                }

                passObject = new GameObject("Sequence instance masks");
                var volume = passObject.AddComponent<CustomPassVolume>();
                volume.isGlobal = true;
                volume.injectionPoint = CustomPassInjectionPoint.BeforeTransparent;
                var observerRenderers = observerRoot == null ? Array.Empty<MeshRenderer>() : observerRoot.GetComponentsInChildren<MeshRenderer>(true);
                if (observerRoot != null && (observerRenderers.Length == 0 || observerRoot.GetComponentsInChildren<SkinnedMeshRenderer>(true).Length > 0 || observerRenderers.Any(r => r.GetComponent<MeshFilter>() == null || r.GetComponent<MeshFilter>().sharedMesh == null || r.sharedMaterials.Any(m => m == null || (m.HasProperty("_SurfaceType") && m.GetFloat("_SurfaceType") != 0) || (m.HasProperty("_AlphaCutoffEnable") && m.GetFloat("_AlphaCutoffEnable") != 0)))))
                    throw new InvalidOperationException("Observer exclusion requires opaque, non-alpha-clipped MeshRenderers; a transparent observer cannot be treated as an opaque ignore area.");
                pass = new DatasetMultiInstanceMaskPass
                {
                    name = "Sequence masks",
                    camera = captureCamera,
                    width = config.width,
                    height = config.height,
                    capacity = plan.maxActive,
                    observerRenderers = observerRenderers,
                    targetColorBuffer = CustomPass.TargetBuffer.None,
                    targetDepthBuffer = CustomPass.TargetBuffer.None
                };
                volume.customPasses.Add(pass);
                if (config.sensors != null && config.sensors.Enabled)
                {
                    var sensorVolume = passObject.AddComponent<CustomPassVolume>();
                    sensorVolume.isGlobal = true;
                    sensorVolume.injectionPoint = CustomPassInjectionPoint.BeforePostProcess;
                    spectral = new DatasetSpectralPass
                    {
                        name = "Synthetic IR and night vision",
                        camera = captureCamera,
                        width = config.width,
                        height = config.height,
                        settings = config.sensors,
                        seed = config.seed,
                        observer = observerRoot == null ? Array.Empty<MeshRenderer>() : observerRoot.GetComponentsInChildren<MeshRenderer>(true),
                        targetColorBuffer = CustomPass.TargetBuffer.None,
                        targetDepthBuffer = CustomPass.TargetBuffer.None
                    };
                    sensorVolume.customPasses.Add(spectral);
                    DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "sensor-models.json"), "{\"thermal\":\"synthetic_surface_temperature_greybody_T4_proxy\",\"night_vision\":\"synthetic_HDR_intensification_green_noise_vignette\",\"radiometrically_calibrated\":false,\"thermal_conduction\":false,\"LWIR_band_integration\":false,\"same_camera_same_geometry_same_render\":true,\"annotations\":\"shared_geometry_not_modality_recognizability\"}");
                }

                exporter = new DatasetSequenceExport(OutputDirectory, sequenceId, config);
                lastRender = queryLastValid = Time.realtimeSinceStartup;
                RenderPipelineManager.endContextRendering += EndRendering;
                running = true;
                SetStatus("warming_up");
                Debug.Log("[Sequence] " + Expected + " images, " + actors.Length + " planned encounters. Seed=" + config.seed + ". Output: " + OutputDirectory);
            }
            catch (Exception exception)
            {
                Fail(exception);
            }
        }

        void Update()
        {
            if (finishing && lotusimSource.CleanupFinished)
            {
                finishing = false;
                SetStatus(lotusimSource.CleanupConfirmed ? "complete" : "complete_cleanup_unconfirmed");
                Debug.Log("[Sequence] " + Status.ToUpperInvariant() + ": " + OutputDirectory);
            }
        }

        void ConfigureRendering()
        {
            priorPipeline = QualitySettings.renderPipeline;
            priorFps = Time.captureFramerate;
            settingsChanged = true;
            QualitySettings.renderPipeline = waterPipeline;
            Time.captureFramerate = config.simulationFps;
            priorTarget = captureCamera.targetTexture;
            target = new RenderTexture(config.width, config.height, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB)
            {
                antiAliasing = 1,
                useDynamicScale = false
            };
            target.Create();
            pixels = new Texture2D(config.width, config.height, TextureFormat.RGB24, false, false);
            captureCamera.targetTexture = target;
            captureCamera.enabled = true;
            captureCamera.fieldOfView = config.verticalFovDeg;
            captureCamera.aspect = (float)config.width / config.height;
            captureCamera.nearClipPlane = .05f;
            captureCamera.farClipPlane = config.farClipM;
            captureCamera.allowDynamicResolution = false;
            var hd = captureCamera.GetComponent<HDAdditionalCameraData>() ?? captureCamera.gameObject.AddComponent<HDAdditionalCameraData>();
            hd.xrRendering = false;
            hd.volumeLayerMask = ~0;
            hd.antialiasing = HDAdditionalCameraData.AntialiasingMode.SubpixelMorphologicalAntiAliasing;
            hd.clearColorMode = HDAdditionalCameraData.ClearColorMode.Sky;
            hd.customRenderingSettings = true;
            hd.renderingPathCustomFrameSettings.SetEnabled(FrameSettingsField.CustomPass, true);
            hd.renderingPathCustomFrameSettingsOverrideMask.mask[(uint)FrameSettingsField.CustomPass] = true;
            profile = environmentVolume.profile;
            Override<WaterRendering>().enable.Override(true);
            var visual = Override<VisualEnvironment>();
            visual.skyType.Override((int)SkyType.PhysicallyBased);
            visual.skyAmbientMode.Override(SkyAmbientMode.Dynamic);
            var sky = Override<PhysicallyBasedSky>();
            sky.updateMode.Override(EnvironmentUpdateMode.Realtime);
            sky.updatePeriod.Override(0);
            // Do not inherit a dark sky multiplier or a second exposure override
            // from the artistic environment. Only modify this runtime instance.
            if (plan.lightingPhases != null)
            {
                environmentVolume.priority = 1000;
                environmentVolume.weight = 1;
                sky.skyIntensityMode.Override(SkyIntensityMode.Exposure);
                sky.exposure.Override(0);
                sky.multiplier.Override(1);
            }

            Override<Exposure>().mode.Override(ExposureMode.Fixed);
            Override<MotionBlur>().intensity.Override(0);
            Override<DepthOfField>().focusMode.Override(DepthOfFieldMode.Off);
            ocean.cpuSimulation = true;
            ocean.cpuFullResolution = true;
            ocean.cpuEvaluateRipples = false;
            ocean.timeMultiplier = 1;
            ocean.absorptionDistance = config.waterOptics.absorptionDistanceM;
            ocean.maxRefractionDistance = config.waterOptics.maxRefractionDistanceM;
            ocean.refractionColor = config.waterOptics.refractionColor;
            ocean.scatteringColor = config.waterOptics.scatteringColor;
            ocean.underWater = true;
            ocean.absorbtionDistanceMultiplier = 1;
            ApplySea(0);
            ocean.largeChaos = .65f;
            ocean.largeBand0FadeToggle = false;
            ocean.largeBand1FadeToggle = false;
            ocean.ripples = true;
            ApplyLighting(0);
            if (plan.manual != null)
            {
                manualWeather = gameObject.AddComponent<DatasetManualWeather>();
                manualWeather.Configure(profile, captureCamera, plan.manual.environment, config.seed);
            }

            heading = Quaternion.Euler(0, config.viewHeadingDeg, 0);
        }

        void ApplySea(float time)
        {
            currentSea = plan.seaEvolution != null && plan.seaEvolution.enabled ? plan.seaEvolution.Evaluate(time, config.seed) : plan.sea;
            ocean.largeWindSpeed = currentSea.windKmh;
            ocean.largeWindOrientationValue = currentSea.directionDeg;
            ocean.largeBand0Multiplier = currentSea.band0;
            ocean.largeBand1Multiplier = currentSea.band1;
            ocean.ripplesWindSpeed = currentSea.ripplesKmh;
            ocean.ripplesWindOrientationValue = currentSea.directionDeg;
            ocean.repetitionSize = currentSea.patchSizeM;
            ocean.simulationFoamAmount = currentSea.foam;
        }

        void PrepareDeckCamera(ScriptableRenderContext context, Camera camera)
        {
            if (!running || camera != captureCamera || observerMotion == null || !observerRoot.activeSelf)
                return;
            // Before HDRP caches its camera matrices (before beginCameraRendering).
            // CPU water is from the previous completed render; both deck and eye
            // use this same frozen sample throughout the next RGB/mask render.
            observerMotion.SampleForCamera(context, camera);
            waterValid = observerMotion.HasValidSample && observerMotion.SampleUnityFrame == Time.frameCount;
            if (!waterValid)
                return;
            queryLastValid = Time.realtimeSinceStartup;
            nominal = observerPose.position + observerPose.rotation * config.observerDeckOffsetM;
            var visual = observerMotion.visual;
            waterNormal = visual.up;
            heave = captureCamera.transform.position.y - nominal.y;
            roll = Mathf.Atan2(captureCamera.transform.right.y, captureCamera.transform.up.y) * Mathf.Rad2Deg;
            pitch = Mathf.Asin(-captureCamera.transform.forward.y) * Mathf.Rad2Deg - config.viewDownPitchDeg;
        }

        void ApplyLighting(int frame)
        {
            int phase = plan.LightingPhaseAt(frame);
            if (phase == lightingPhase)
                return;
            bool changed = lightingPhase >= 0;
            lightingPhase = phase;
            currentLight = plan.lightingPhases == null ? plan.light : plan.lightingPhases[phase].light;
            sun.enabled = true;
            sun.shadows = LightShadows.Soft;
            RenderSettings.sun = sun;
            sun.transform.rotation = Quaternion.LookRotation(-DatasetCampaignConfig.OrbitOffset(1, config.viewHeadingDeg + currentLight.relativeBearingDeg, currentLight.elevationDeg), Vector3.up);
            var hl = sun.GetComponent<HDAdditionalLightData>() ?? sun.gameObject.AddComponent<HDAdditionalLightData>();
            if (plan.lightingPhases != null)
            {
                hl.SetLightDimmer(1, 1);
                hl.interactsWithSky = true;
                sun.color = Color.white;
            }

            hl.SetIntensity(currentLight.intensityLux, LightUnit.Lux);
            sun.useColorTemperature = true;
            sun.colorTemperature = currentLight.temperatureKelvin;
            var exposure = Override<Exposure>();
            exposure.fixedExposure.Override(currentLight.exposureEV100);
            if (plan.lightingPhases != null)
                exposure.compensation.Override(0);
            // Let sky/reflections settle without advancing LOTUSim or losing an
            // image at a phase boundary. This is not a 24-hour astronomical model.
            lightingWarmup = changed && plan.lightingPhases != null ? config.lighting.settleFrames : 0;
            lightingWarmupFrame = -1;
            if (changed && plan.lightingPhases != null)
            {
                // A lighting cut spans many exposure stops. Old pre-exposure /
                // reflection histories otherwise flash on the water surface.
                HDCamera.GetOrCreate(captureCamera).Reset();
                (RenderPipelineManager.currentPipeline as HDRenderPipeline)?.RequestSkyEnvironmentUpdate();
            }

            Debug.Log("[Sequence] Lighting " + currentLight.name + " (" + currentLight.illuminant + ") at source frame " + frame + ", EV100=" + currentLight.exposureEV100);
        }

        T Override<T>()
            where T : VolumeComponent
        {
            if (!profile.TryGet<T>(out var c))
                c = profile.Add<T>();
            c.active = true;
            return c;
        }

        void CreateActors()
        {
            actors = new DatasetSequenceActor[plan.events.Length];
            for (int i = 0; i < actors.Length; i++)
            {
                var e = plan.events[i];
                var definition = config.classes[e.classIndex];
                var root = Instantiate(DatasetBoatVariants.Resolve(definition, e));
                root.name = e.instance;
                root.SetActive(false);
                var actor = new DatasetSequenceActor
                {
                    root = root,
                    encounter = e,
                    definition = definition,
                    visual = root.transform
                };
                actors[i] = actor;
                actor.assetLights = root.GetComponent<DatasetAssetLights>();
                if (actor.assetLights != null)
                    actor.assetLights.externalClock = true;
                actor.meshAnimation = root.GetComponent<DatasetMeshAnimation>();
                if (actor.meshAnimation != null)
                    actor.meshAnimation.externalClock = true;
                actor.aerialResponse = root.GetComponent<DatasetAerialResponse>();
                if (actor.aerialResponse != null)
                {
                    actor.aerialResponse.externalClock = true;
                    actor.visual = actor.aerialResponse.visual;
                }

                actor.marineMotion = root.GetComponent<MarineVesselWaveMotion>();
                if (actor.marineMotion != null)
                {
                    actor.marineMotion.Configure(ocean, captureCamera, true);
                    actor.visual = actor.marineMotion.visual;
                }
                else if (definition.moored)
                {
                    actor.visual = root.transform.Find(BuoyWaveMotion.VisualChildName);
                    if (actor.visual == null)
                        throw new InvalidOperationException("Buoy visual marker missing.");
                    actor.flotation = root.AddComponent<BuoyWaveMotion>();
                    actor.flotation.Configure(ocean, actor.visual, captureCamera, config.flotation);
                    // Audited built-ins retain the strict required lamp. A
                    // user-imported buoy may legitimately have no beacon;
                    // do not invent one or fail flotation for that reason.
                    if (root.GetComponent<DatasetImportedAsset>() == null || actor.visual.GetComponentsInChildren<MeshRenderer>(true).Any(r => r.name == "AmberFresnelLens"))
                    {
                        actor.lantern = root.AddComponent<BuoyLanternFlash>();
                        actor.lantern.Configure(actor.visual, captureCamera, config.lantern);
                    }
                }
                else if (definition.category != "bird" && actor.assetLights == null)
                {
                    actor.lights = root.AddComponent<DatasetAircraftLights>();
                    actor.lights.Configure(definition.category, e.phase);
                }

                var renderers = root.GetComponentsInChildren<MeshRenderer>(true);
                if (renderers.Length == 0 || root.GetComponentsInChildren<SkinnedMeshRenderer>(true).Length > 0 || renderers.Any(r => r.GetComponent<MeshFilter>() == null || r.GetComponent<MeshFilter>().sharedMesh == null || r.sharedMaterials.Any(m => m == null || (m.HasProperty("_SurfaceType") && m.GetFloat("_SurfaceType") != 0) || (m.HasProperty("_AlphaCutoffEnable") && m.GetFloat("_AlphaCutoffEnable") != 0))))
                    throw new InvalidOperationException("Sequence requires opaque, non-alpha-clipped MeshRenderers: " + e.instance);
                actor.mask = new DatasetMaskTarget
                {
                    renderers = renderers
                };
            }
        }

        void LateUpdate()
        {
            if (!running)
                return;
            try
            {
                if (pass.Error != null)
                    throw new InvalidOperationException(pass.Error);
                if (spectral?.Error != null)
                    throw new InvalidOperationException(spectral.Error);
                if (lotusimSource != null)
                {
                    if (lotusimSource.Error != null)
                        throw new InvalidOperationException(lotusimSource.Error);
                    if (!lotusimSource.HasFrame)
                    {
                        lastRender = Time.realtimeSinceStartup;
                        pass.armed = false;
                        if (spectral != null)
                            spectral.armed = false;
                        preparedFrame = -1;
                        SetStatus("lotusim_" + lotusimSource.Status);
                        return;
                    }

                    if (lotusimSource.Current.frame != simulationFrame)
                        throw new InvalidOperationException("LOTUSim frame acknowledgement is out of sequence.");
                }

                if (Time.realtimeSinceStartup - lastRender > config.renderTimeoutSeconds)
                    throw new TimeoutException("Sequence camera stopped rendering.");
                ApplyLighting(simulationFrame);
                float time = lotusimSource == null ? simulationFrame / (float)config.simulationFps : (float)lotusimSource.Current.timeSeconds;
                ApplySea(time);
                heading = Quaternion.Euler(0, config.ViewHeading(time), 0);
                if (lotusimSource == null)
                    nominal = config.ObserverNominal(time);
                else
                {
                    var observer = lotusimSource.Current.objects.Single(o => o.instance == DatasetLotusimScenario.Observer);
                    if (observer.model != DatasetLotusimScenario.ObserverModel)
                        throw new InvalidOperationException("LOTUSim observer model mismatch: export the FREMM scenario with Dataset menu 7.");
                    observerPose = observer.UnityPose;
                    observerRoot.SetActive(true);
                    observerRoot.transform.SetPositionAndRotation(observerPose.position, observerPose.rotation);
                    nominal = config.observerDeckCamera ? observerPose.position + observerPose.rotation * config.observerDeckOffsetM : observerPose.position + Vector3.up * config.observerHeightM;
                }

                if (observerMotion == null)
                    SampleObserverWater(nominal);
                else
                    PrepareDeckCamera(default(ScriptableRenderContext), captureCamera);
                if (warmup >= config.warmupFrames && Time.realtimeSinceStartup - queryLastValid > config.renderTimeoutSeconds)
                    throw new TimeoutException("Observer CPU water query unavailable/non-convergent.");
                if (observerMotion == null)
                    captureCamera.transform.SetPositionAndRotation(nominal + Vector3.up * heave, heading * Quaternion.Euler(config.viewDownPitchDeg + pitch, 0, roll));
                var current = new List<DatasetSequenceActor>();
                foreach (var actor in actors)
                {
                    var source = lotusimSource == null ? null : lotusimSource.Current.objects.FirstOrDefault(o => o.instance == actor.encounter.instance);
                    bool enabled = lotusimSource == null ? actor.encounter.Active(time) : source != null;
                    if (actor.root.activeSelf != enabled)
                        actor.root.SetActive(enabled);
                    if (!enabled)
                        continue;
                    if (source == null)
                    {
                        actor.root.transform.position = actor.encounter.Position(time);
                        if (!actor.definition.moored)
                            actor.root.transform.rotation = Quaternion.LookRotation(actor.encounter.Velocity(time).normalized, Vector3.up) * Quaternion.Euler(0, -90, 0);
                        actor.sourceVelocity = actor.encounter.Velocity(time);
                    }
                    else
                    {
                        if (source.model != DatasetBoatVariants.Resolve(actor.definition, actor.encounter).name)
                            throw new InvalidOperationException("LOTUSim model/class mismatch: " + source.instance);
                        var pose = source.UnityPose;
                        actor.root.transform.SetPositionAndRotation(pose.position, pose.rotation);
                        actor.sourceVelocity = source.UnityVelocity;
                        actor.sourceEntity = source.entity;
                    }

                    actor.sourcePose = new Pose(actor.root.transform.position, actor.root.transform.rotation);
                    actor.lights?.Apply(time);
                    actor.assetLights?.Apply(time, actor.encounter.phase);
                    actor.meshAnimation?.Apply(time + actor.encounter.phase);
                    actor.aerialResponse?.Apply(time, actor.encounter.phase, actor.encounter.VisualBankDeg(time));
                    current.Add(actor);
                }

                if (lotusimSource != null && lotusimSource.Current.objects.Length != current.Count + 1)
                    throw new InvalidOperationException("LOTUSim snapshot contains an unregistered actor.");
                active = current.ToArray();
                if (lotusimSource != null)
                    DatasetTrafficRuntimeGuard.Check(config, plan, time, active, observerPose);
                pass.targets = active.Select(a => a.mask).ToArray();
                pass.armed = warmup >= config.warmupFrames && config.ShouldCapture(simulationFrame);
                preparedFrame = Time.frameCount;
                if (spectral != null)
                {
                    spectral.actors = active;
                    spectral.sourceFrame = simulationFrame;
                    spectral.armed = pass.armed;
                }
            }
            catch (Exception exception)
            {
                Fail(exception);
            }
        }

        void SampleObserverWater(Vector3 point)
        {
            var heights = new float[5];
            waterValid = false;
            for (int i = 0; i < 5; i++)
            {
                Vector3 offset = i == 1 ? Vector3.left : i == 2 ? Vector3.right : i == 3 ? Vector3.back : i == 4 ? Vector3.forward : Vector3.zero;
                var query = new WaterSearchParameters
                {
                    targetPosition = point + offset,
                    startPosition = point + offset,
                    error = .01f,
                    maxIterations = 16
                };
                if (!ocean.FindWaterSurfaceHeight(query, out var sample) || float.IsNaN(sample.height) || float.IsInfinity(sample.height) || float.IsNaN(sample.error) || float.IsInfinity(sample.error) || sample.error > .05f)
                    return;
                heights[i] = sample.height;
            }

            waterNormal = BuoyWaveMotion.NormalFromHeights(heights[1], heights[2], heights[3], heights[4], 1);
            var n = Quaternion.Inverse(heading) * waterNormal;
            float wantedPitch = Mathf.Clamp(Mathf.Atan2(n.z, n.y) * Mathf.Rad2Deg * config.waterTiltGain, -config.maxPitchDeg, config.maxPitchDeg);
            float wantedRoll = Mathf.Clamp(-Mathf.Atan2(n.x, n.y) * Mathf.Rad2Deg * config.waterTiltGain, -config.maxRollDeg, config.maxRollDeg);
            float blend = BuoyWaveMotion.ResponseBlend(config.responsePerSecond, Time.deltaTime);
            pitch = Mathf.Lerp(pitch, wantedPitch, blend);
            roll = Mathf.Lerp(roll, wantedRoll, blend);
            heave = Mathf.Lerp(heave, Mathf.Clamp((heights[0] - config.origin.y) * config.heaveGain, -config.maxHeaveM, config.maxHeaveM), blend);
            waterValid = true;
            queryLastValid = Time.realtimeSinceStartup;
        }

        void EndRendering(ScriptableRenderContext context, List<Camera> cameras)
        {
            if (!running || !cameras.Contains(captureCamera) || lastRenderedUnityFrame == Time.frameCount)
                return;
            lastRenderedUnityFrame = Time.frameCount;
            lastRender = Time.realtimeSinceStartup;
            try
            {
                if (preparedFrame != Time.frameCount)
                    return;
                if (warmup < config.warmupFrames)
                {
                    warmup++;
                    return;
                }

                if (lightingWarmup > 0)
                {
                    // Count actual Unity frames, not repeated renders of one
                    // frame (e.g. an editor preview or an explicit render).
                    if (lightingWarmupFrame != Time.frameCount)
                    {
                        lightingWarmupFrame = Time.frameCount;
                        lightingWarmup--;
                    }

                    return;
                }

                if (!waterValid || active.Any(a => (a.flotation != null && config.flotation.enabled && (!a.flotation.HasValidSample || a.flotation.SampleUnityFrame != Time.frameCount)) || (a.marineMotion != null && a.marineMotion.enabled && (!a.marineMotion.HasValidSample || a.marineMotion.SampleUnityFrame != Time.frameCount))))
                    return;
                if (config.ShouldCapture(simulationFrame))
                {
                    if (pass.Error != null)
                        throw new InvalidOperationException(pass.Error);
                    if (pass.Frame != Time.frameCount)
                        throw new InvalidOperationException("Sequence masks did not render in the RGB frame.");
                    if (spectral != null && (spectral.Error != null || spectral.Frame != Time.frameCount))
                        throw new InvalidOperationException(spectral.Error ?? "Synthetic sensors did not render in the RGB frame.");
                    var previous = RenderTexture.active;
                    try
                    {
                        RenderTexture.active = target;
                        pixels.ReadPixels(new Rect(0, 0, config.width, config.height), 0, 0, false);
                        pixels.Apply(false, false);
                    }
                    finally
                    {
                        RenderTexture.active = previous;
                    }

                    var frame = new DatasetSequenceFrame
                    {
                        sequenceId = sequenceId,
                        imageId = "f" + Captured.ToString("D6"),
                        imageIndex = Captured,
                        seed = config.seed,
                        width = config.width,
                        height = config.height,
                        unityFrame = Time.frameCount,
                        simulationFrame = simulationFrame,
                        sequenceTimeSeconds = simulationFrame / (float)config.simulationFps,
                        unityWaterTimeSeconds = Time.time,
                        manualCampaign = plan.manual,
                        cameraPosition = captureCamera.transform.position,
                        cameraRotation = captureCamera.transform.rotation,
                        cameraNominalPosition = nominal,
                        cameraRollDeg = roll,
                        cameraPitchDeg = pitch,
                        cameraHeaveM = heave,
                        waterNormal = waterNormal,
                        waterQueryValid = waterValid,
                        cameraWaterSampleFrame = preparedFrame,
                        cameraWaterSampleFromPreviousRender = true,
                        cameraMount = observerMotion == null ? "elevated observer" : "FREMM " + config.observerCameraStation + " / rigid mount / no horizon stabilization",
                        observerHeadingDeg = config.ObserverHeading(simulationFrame / (float)config.simulationFps),
                        viewMatrix = Matrix(captureCamera.worldToCameraMatrix),
                        projectionMatrix = Matrix(captureCamera.projectionMatrix),
                        sea = currentSea,
                        light = currentLight,
                        lightingPhaseIndex = lightingPhase,
                        lightingTimeOfDay = plan.lightingPhases == null ? "" : plan.lightingPhases[lightingPhase].timeOfDay,
                        activeObjects = active.Select(a => new DatasetSequenceObjectState { instance = a.encounter.instance, trackId = a.encounter.trackId, category = a.definition.category, modelName = DatasetBoatVariants.Resolve(a.definition, a.encounter).name, plannedFlightMode = a.encounter.flightMode, plannedSpeedKmh = a.encounter.velocity.magnitude * 3.6f, plannedYawRateDegS = a.encounter.yawRateDegS, motionModel = lotusimSource == null ? (a.definition.moored ? "Unity moored visual flotation" : "Unity constant-velocity crossing") : (a.definition.moored ? "LOTUSim moored root + Unity visual flotation" : "LOTUSim kinematic trajectory"), position = a.visual.position, rotation = a.visual.rotation, velocity = a.sourceVelocity, sourceRootPosition = a.sourcePose.position, sourceRootRotation = a.sourcePose.rotation, sourceEntity = a.sourceEntity, cameraDistanceM = Vector3.Distance(captureCamera.transform.position, a.visual.position), flotationSampleUnityFrame = a.marineMotion != null ? a.marineMotion.SampleUnityFrame : a.flotation == null ? -1 : a.flotation.SampleUnityFrame, flotationModel = a.marineMotion == null ? "" : "HDRP nine-point damped vessel response; ROS root unchanged", vesselHeaveM = a.marineMotion == null ? 0 : a.marineMotion.HeaveM, vesselRollDeg = a.marineMotion == null ? 0 : a.marineMotion.RollDeg, vesselPitchDeg = a.marineMotion == null ? 0 : a.marineMotion.PitchDeg, syntheticThermalPrior = config.sensors?.thermal == true, assumedSurfaceTemperatureC = config.sensors?.thermal == true ? config.sensors.Profile(a.definition.category).temperatureC : 0, assumedEmissivity = config.sensors?.thermal == true ? config.sensors.Profile(a.definition.category).emissivity : 0, meshAnimationFrame = a.meshAnimation == null ? -1 : a.meshAnimation.Frame, animationModel = a.meshAnimation == null ? "" : a.meshAnimation.clip.provenance, visualFlightResponse = a.aerialResponse == null ? "" : (a.encounter.boundedTurn ? "visual coordinated-bank and gust effects; not flight dynamics; ROS root unchanged" : "visual gust perturbation only; not aerodynamic simulation; ROS root unchanged"), lights = a.assetLights != null ? a.assetLights.State : a.lights == null ? Array.Empty<DatasetAircraftLightState>() : a.lights.State, lanternLevel = a.lantern == null ? 0 : a.lantern.Level }).ToArray()
                    };
                    frame.motionSource = MotionSource;
                    if (plan.traffic != null)
                    {
                        frame.hasTrafficWeather = true;
                        frame.seaWindIsSpectrumProxy = true;
                        frame.localWindMps = plan.traffic.localWindMps;
                        frame.requestedSwellHeightM = plan.traffic.significantSwellHeightM;
                        frame.trafficPlanSha256 = plan.traffic.inputSha256;
                        frame.trafficPlannerSha256 = plan.traffic.plannerSha256;
                    }

                    if (lotusimSource != null)
                    {
                        frame.lotusimRunId = lotusimSource.RunId;
                        frame.lotusimPlanId = lotusimSource.Current.planId;
                        frame.lotusimWorldTimeSeconds = lotusimSource.Current.worldTimeSeconds;
                        frame.rosConnectionInstanceId = lotusimSource.ConnectionInstanceId;
                        frame.observerRootPosition = observerPose.position;
                        frame.observerRootRotation = observerPose.rotation;
                        if (observerMotion != null)
                        {
                            frame.cameraLocalMountPosition = captureCamera.transform.localPosition;
                            frame.cameraLocalMountRotation = captureCamera.transform.localRotation;
                            frame.observerVisualPosition = observerMotion.visual.position;
                            frame.observerVisualRotation = observerMotion.visual.rotation;
                            frame.observerRollDeg = observerMotion.RollDeg;
                            frame.observerPitchDeg = observerMotion.PitchDeg;
                        }

                        DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "annotations", frame.imageId + ".lotusim.json"), lotusimSource.CurrentJson);
                    }

                    exporter.Export(pixels, pass, active, frame, spectral);
                    SetStatus("capturing");
                    if (Captured == 1 || Captured % 30 == 0)
                    {
                        exporter.FinalizeIndex();
                        Debug.Log("[Sequence] " + Captured + " / " + Expected + "; boxes=" + Boxes);
                    }
                }

                simulationFrame++;
                if (simulationFrame >= config.SimulationFrames || (config.manualPlan != null && Captured == Expected))
                {
                    if (Captured != Expected)
                        throw new InvalidOperationException("Sequence image count mismatch.");
                    exporter.FinalizeIndex();
                    running = false;
                    RenderPipelineManager.endContextRendering -= EndRendering;
                    if (lotusimSource == null)
                    {
                        SetStatus("complete");
                        Debug.Log("[Sequence] COMPLETE: " + OutputDirectory);
                    }
                    else
                    {
                        finishing = true;
                        SetStatus("stopping_owned_scenario");
                        lotusimSource.StopOwned();
                    }
                }
                else if (lotusimSource != null)
                    lotusimSource.RequestFrame(simulationFrame);
            }
            catch (Exception exception)
            {
                Fail(exception);
            }
        }

        static float[] Matrix(Matrix4x4 matrix)
        {
            var result = new float[16];
            for (int i = 0; i < 16; i++)
                result[i] = matrix[i];
            return result;
        }

        void SetStatus(string status)
        {
            if (Status == status)
                return;
            Status = status;
            if (OutputDirectory != null)
                DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "status.json"), JsonUtility.ToJson(new StatusRecord { status = Status, error = error, sequenceId = sequenceId, captured = Captured, expected = Expected, boxes = Boxes, motionSource = MotionSource }, true));
        }

        void Fail(Exception exception)
        {
            running = false;
            error = exception.ToString();
            RenderPipelineManager.endContextRendering -= EndRendering;
            lotusimSource?.CancelOwned();
            try
            {
                if (OutputDirectory != null && !string.IsNullOrEmpty(lotusimSource?.LastResponse))
                    DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "lotusim-last-response.txt"), lotusimSource.LastResponse);
                exporter?.FinalizeIndex();
                SetStatus("failed");
            }
            catch (Exception io)
            {
                Debug.LogWarning("[Sequence] Report failure: " + io.Message);
            }

            Debug.LogError("[Sequence] FAILED: " + exception + ". Completed files remain in " + OutputDirectory);
        }

        void OnDisable()
        {
            RenderPipelineManager.endContextRendering -= EndRendering;
            if (running)
            {
                running = false;
                try
                {
                    exporter?.FinalizeIndex();
                    SetStatus("cancelled");
                }
                catch (Exception e)
                {
                    Debug.LogWarning(e.Message);
                }
            }

            if (settingsChanged)
            {
                QualitySettings.renderPipeline = priorPipeline;
                Time.captureFramerate = priorFps;
                settingsChanged = false;
            }

            if (actors != null)
                foreach (var actor in actors)
                    if (actor != null && actor.root != null)
                        Destroy(actor.root);
            if (cameraMount != null)
            {
                cameraMount.Detach();
                Destroy(cameraMount);
            }

            if (manualWeather != null)
            {
                manualWeather.enabled = false;
                Destroy(manualWeather);
            }

            if (observerRoot != null)
                Destroy(observerRoot);
            lotusimSource?.CancelOwned();
            if (passObject != null)
                Destroy(passObject);
            if (exporter != null)
            {
                captured = exporter.Count;
                boxes = exporter.Boxes;
                exporter.Dispose();
                exporter = null;
            }

            if (captureCamera != null && target != null)
                captureCamera.targetTexture = priorTarget;
            if (target != null)
            {
                target.Release();
                Destroy(target);
            }

            if (pixels != null)
                Destroy(pixels);
            if (config != null)
                Destroy(config);
        }
    }
}
