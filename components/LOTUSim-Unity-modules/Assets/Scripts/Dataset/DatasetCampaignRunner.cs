using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using RosMessageTypes.Lotusim;
using RosMessageTypes.Std;
using Unity.Robotics.ROSTCPConnector;
using Unity.Robotics.ROSTCPConnector.MessageGeneration;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace Lotusim.Dataset
{
    [DefaultExecutionOrder(-5000)]
    public sealed class DatasetCampaignRunner : MonoBehaviour
    {
        public DatasetCampaignConfig configuration;
        public Camera captureCamera;
        public WaterSurface ocean;
        public Light sun;
        public Volume environmentVolume;
        public HDRenderPipelineAsset waterPipeline;
        public GameObject rosRoot;
        public bool autoStart=true;
        public string Status {get;private set;}="idle";
        public string OutputDirectory {get;private set;}
        public int Captured {get;private set;}
        public int Expected {get;private set;}
        public int AnnotatedFrames=>m_annotations!=null?m_annotations.Count:m_runStatus==null?0:m_runStatus.annotatedFrames;
        public int AnnotationBoxes=>m_annotations!=null?m_annotations.Boxes:m_runStatus==null?0:m_runStatus.annotationBoxes;
        public RenderTexture Preview=>m_targetTexture;

        DatasetCampaignConfig m_config;
        GameObject m_target,m_localObject;
        Vector3 m_targetStart,m_aimOffset,m_meanAim;
        Quaternion m_targetRotation;
        Transform m_visual;
        BuoyWaveMotion m_waveMotion;
        bool m_ownsWaveMotion;
        BuoyLanternFlash m_lantern;
        ROSConnection m_ros;
        Task m_stopTask;
        bool m_ownsScenario,m_captureArmed,m_running,m_receivedPose;
        int m_poseMessages,m_targetPoseMessages;
        string[] m_lastPoseNames=Array.Empty<string>();
        int m_renderedFrames,m_rosSec;
        uint m_rosNanosec;
        float m_lastRenderRealtime;
        float m_maskRequestedRealtime;
        Exception m_captureError;
        RenderTexture m_targetTexture,m_previousTarget;
        Texture2D m_pixels;
        int m_previousCaptureFps;
        RenderPipelineAsset m_previousPipeline;
        bool m_settingsChanged;
        VolumeProfile m_profile;
        DatasetCondition m_condition;
        DatasetInstanceMaskPass m_maskPass;
        GameObject m_maskRoot;
        DatasetAnnotationExport m_annotations;
        Vector3 m_nominalCameraPosition;
        Quaternion m_nominalCameraRotation;
        Vector2 m_cameraPitchRoll;
        double m_cameraMotionStartTime;
        float m_cameraMotionElapsed;
        int m_cameraMotionFrame=-1;
        bool m_cameraPoseReady;
        int m_sample;
        readonly List<string> m_files=new List<string>();

        [Serializable] sealed class RunStatus {
            public string schema="lotusim-rgb-pilot-1",status,outputDirectory,error="",startedUtc,updatedUtc;
            public string errorDetails="";
            public bool capturesComplete;
            public string scenarioCleanupWarning="";
            public int expected,captured;
            public bool annotationsProduced=false,scenarioOwned,scenarioStopConfirmed;
            public int annotatedFrames,annotationBoxes;
            public string annotationPolicy="disabled";
            public string[] images;
            public string scenarioLaunchResponse="",targetReadiness="",lastPoseNames="";
            public int poseMessages,targetPoseMessages;
        }
        RunStatus m_runStatus;

        [Serializable] sealed class FrameInfo {
            public string schema="lotusim-rgb-frame-2",imageId,imageFile,utc,renderSource="Unity HDRP",objectSource;
            public string instance,model,category,displayName,annotationStatus="not_generated",seaHeightConvention="uncalibrated_presets";
            public int classId,conditionIndex,sampleIndex,seed,width,height,unityFrame,rosStampSec,renderedFrame;
            public uint rosStampNanosec;
            public bool rosPoseStampAvailable,waterQueryAvailable,waterQueryIncludesRipples;
            public float simulationTimeSeconds,waterTimeMultiplier,verticalFovDeg,distanceRequestedM,distanceAppliedM;
            public float azimuthDeg,elevationDeg,waterHeightAtTargetM,exposureAppliedEV100,sunAppliedLux;
            public Vector3 cameraPosition,targetPosition,aimPoint,sunRayDirection;
            public Quaternion cameraRotation,targetRotation;
            public float[] viewMatrix,projectionMatrix,gpuProjectionMatrix;
            public DatasetSeaPreset seaRequested,seaApplied;
            public DatasetLightPreset lightRequested;
            public string motionModel="static",cameraOrbitReference="fixed_mean_anchor";
            public bool visualFlotationEnabled;
            public int flotationSampleUnityFrame=-1;
            public float flotationMeanWaterHeightM,flotationHeaveM,flotationTiltDeg,flotationMaxQueryErrorM;
            public Vector3 anchorPosition,flotationSurfaceNormal;
            public Quaternion anchorRotation;
            public DatasetFlotationSettings flotationRequested;
            public DatasetWaterOpticsSettings waterOpticsRequested,waterOpticsApplied;
            public DatasetLanternSettings lanternRequested;
            public bool lanternOn;
            public float lanternLevel,lanternPhaseSeconds,lanternLightLumens;
            public int lanternSampleUnityFrame=-1;
            public string cameraMotionModel="fixed";
            public DatasetCameraMotionSettings cameraMotionRequested;
            public Vector3 cameraNominalPosition;
            public Quaternion cameraNominalRotation;
            public float cameraPitchDeg,cameraRollDeg,cameraMotionElapsedSeconds,cameraMotionSeaScale;
            public int cameraMotionSampleUnityFrame=-1;
            public string annotationFile="",visibleMaskFile="",annotationOverlayFile="";
        }

        void Awake()
        {
            if(configuration!=null&&configuration.objectSource==DatasetObjectSource.LocalPreview&&rosRoot!=null)
                rosRoot.SetActive(false);
        }

        void Start() {if(autoStart) StartCampaign();}

        void LateUpdate()
        {
            if(!m_running||!m_cameraPoseReady||m_condition==null||m_config==null||captureCamera==null) return;
            // Apply before HDRP builds camera/culling matrices, not inside
            // beginCameraRendering (which is too late for camera pose changes).
            m_cameraMotionElapsed=(float)(Time.timeAsDouble-m_cameraMotionStartTime);
            m_cameraPitchRoll=m_config.cameraMotion.Angles(m_cameraMotionElapsed,m_config.seed,m_condition.index,m_condition.sea.cameraMotionScale);
            DatasetCameraMotionSettings.ApplyPose(captureCamera,m_nominalCameraPosition,m_nominalCameraRotation,m_cameraPitchRoll);
            m_cameraMotionFrame=Time.frameCount;
            if(m_captureArmed&&m_maskPass!=null) m_maskPass.armed=true;
        }

        [ContextMenu("Start campaign")]
        public void StartCampaign()
        {
            if(m_running||Status!="idle") {Debug.LogWarning("[Dataset] This runner has already started. Enter a fresh Play session to run again.");return;}
            m_running=true;StartCoroutine(GuardedCampaign());
        }

        IEnumerator GuardedCampaign()
        {
            var operation=Campaign();
            while(true) {
                bool next;object yielded=null;
                try {next=operation.MoveNext();if(next) yielded=operation.Current;}
                catch(Exception exception) {Fail(exception);yield break;}
                if(!next) yield break;
                yield return yielded;
            }
        }

        IEnumerator Campaign()
        {
            if(configuration==null) throw new InvalidOperationException("Assign a campaign configuration.");
            m_config=Instantiate(configuration);m_config.Validate();
            if(captureCamera==null||ocean==null||sun==null||environmentVolume==null||waterPipeline==null)
                throw new InvalidOperationException("Missing dataset camera, ocean, sun, volume or water-enabled HDRP asset.");
            if(!waterPipeline.currentPlatformRenderPipelineSettings.supportWater)
                throw new InvalidOperationException("The selected HDRP asset does not support water.");
            if(m_config.flotation.enabled&&!waterPipeline.currentPlatformRenderPipelineSettings.waterCPUSimulation)
                throw new InvalidOperationException("Enable Water Script Interactions in the capture HDRP asset for flotation.");
            if(m_config.annotations.enabled&&!waterPipeline.currentPlatformRenderPipelineSettings.supportCustomPass)
                throw new InvalidOperationException("Enable Custom Pass in the capture HDRP asset for annotations.");
            Expected=m_config.ImageCount();
            string root=Path.IsPathRooted(m_config.outputRoot)?m_config.outputRoot:Path.Combine(Application.dataPath,"..",m_config.outputRoot);
            OutputDirectory=Path.GetFullPath(Path.Combine(root,"buoy_"+DateTime.UtcNow.ToString("yyyyMMdd_HHmmss")+"_"+Guid.NewGuid().ToString("N").Substring(0,8)));
            Directory.CreateDirectory(Path.Combine(OutputDirectory,"rgb"));Directory.CreateDirectory(Path.Combine(OutputDirectory,"metadata"));
            m_runStatus=new RunStatus{expected=Expected,outputDirectory=OutputDirectory,startedUtc=DateTime.UtcNow.ToString("O")};
            AtomicWrite(Path.Combine(OutputDirectory,"requested-config.json"),JsonUtility.ToJson(m_config,true));
            AtomicWrite(Path.Combine(OutputDirectory,"provenance.json"),"{\"unity\":\""+Application.unityVersion+"\",\"renderer\":\"HDRP 14\",\"annotations\":"+(m_config.annotations.enabled?"true":"false")+",\"annotation_policy\":\"nearest_depth_water_is_opaque\",\"pixel_replay_guaranteed\":false,\"gazebo_hydrodynamics\":false}");
            SetupRendering();
            SetStatus("waiting_for_object");

            if(m_config.objectSource==DatasetObjectSource.LocalPreview) {
                if(m_config.localPreviewPrefab==null) throw new InvalidOperationException("Local preview prefab is missing.");
                m_localObject=Instantiate(m_config.localPreviewPrefab,m_config.localPreviewPosition,Quaternion.identity);
                m_localObject.name=m_config.targetName;m_target=m_localObject;
            }
            else {
                m_ros=ROSConnection.GetOrCreateInstance();
                float deadline=Time.realtimeSinceStartup+m_config.connectionTimeoutSeconds;
                SetStatus("waiting_for_ros");
                while(!m_ros.HasConnectionThread||m_ros.HasConnectionError||RosInterface.Instance.RosNamespace!=m_config.rosNamespace.Trim('/')) {
                    if(Time.realtimeSinceStartup>deadline) throw new TimeoutException("ROS connection/subscriptions are not ready. Check LOTUSim and the ROS TCP endpoint.");
                    yield return null;
                }
                // Use the connector's exact topic key: a second spelling with a leading
                // slash would create another subscription to the same canonical ROS topic.
                m_ros.Subscribe<VesselPositionArrayMsg>(m_config.rosNamespace.Trim('/')+"/renderer_poses",OnSourcePose);
                if(m_config.launchScenario) {
                    MessageRegistry.Register(DatasetStringRequest.RosName,DatasetStringRequest.Deserialize);
                    MessageRegistry.Register(DatasetStringRequest.RosName,DatasetStringResponse.Deserialize,MessageSubtopic.Response);
                    string service="/"+m_config.rosNamespace.Trim('/')+"/launch_scenario";
                    m_ros.RegisterRosService<DatasetStringRequest,DatasetStringResponse>(service);
                    SetStatus("launching_scenario");
                    Task<DatasetStringResponse> launch=m_ros.SendServiceMessage<DatasetStringResponse>(service,new DatasetStringRequest(m_config.scenarioFile));
                    deadline=Time.realtimeSinceStartup+m_config.objectTimeoutSeconds;
                    while(!launch.IsCompleted) {if(Time.realtimeSinceStartup>deadline) throw new TimeoutException("Scenario launch response timed out; ownership is unconfirmed. Inspect LOTUSim before retrying.");yield return null;}
                    if(launch.IsFaulted) throw launch.Exception;
                    m_runStatus.scenarioLaunchResponse=launch.Result.message;
                    Debug.Log("[Dataset] LOTUSim launch response: "+launch.Result.success+" — "+launch.Result.message);
                    if(!launch.Result.success) throw new InvalidOperationException("LOTUSim refused the scenario: "+launch.Result.message+". No existing scenario was stopped.");
                    m_ownsScenario=true;
                }
                SetStatus("waiting_for_object");deadline=Time.realtimeSinceStartup+m_config.objectTimeoutSeconds;
                while((m_target=GameObject.Find(m_config.targetName))==null||m_target.GetComponentsInChildren<MeshRenderer>().Length==0||!m_receivedPose) {
                    if(Time.realtimeSinceStartup>deadline) throw new TimeoutException(TargetReadiness());
                    yield return null;
                }
            }
            var renderers=m_target.GetComponentsInChildren<MeshRenderer>().Where(r=>r.enabled&&r.gameObject.activeInHierarchy).ToArray();
            if(renderers.Length==0) throw new InvalidOperationException("The target has no active renderer.");
            if(m_config.annotations.enabled) {
                foreach(var renderer in renderers) foreach(var material in renderer.sharedMaterials)
                    if(material!=null&&((material.HasProperty("_SurfaceType")&&material.GetFloat("_SurfaceType")!=0)||
                        (material.HasProperty("_AlphaCutoffEnable")&&material.GetFloat("_AlphaCutoffEnable")!=0)))
                        throw new InvalidOperationException("This annotation pass supports opaque, non-alpha-clipped target meshes only.");
                m_maskRoot=new GameObject("Dataset instance-mask pass");
                var volume=m_maskRoot.AddComponent<CustomPassVolume>();volume.isGlobal=true;volume.injectionPoint=CustomPassInjectionPoint.BeforeTransparent;
                m_maskPass=new DatasetInstanceMaskPass{name="Dataset geometric instance masks",captureCamera=captureCamera,targetRenderers=renderers,
                    width=m_config.width,height=m_config.height,targetColorBuffer=CustomPass.TargetBuffer.None,targetDepthBuffer=CustomPass.TargetBuffer.None};
                volume.customPasses.Add(m_maskPass);
                m_annotations=new DatasetAnnotationExport(OutputDirectory,m_config.width,m_config.height,m_config.targetName,m_config.category,m_config.classId,m_config.annotations);
                m_runStatus.annotationPolicy="nearest_depth_water_is_opaque";
            }
            var bounds=renderers[0].bounds;foreach(var renderer in renderers.Skip(1)) bounds.Encapsulate(renderer.bounds);
            // Aim at the exposed body, not the submerged mooring chain.
            m_visual=m_target.transform.Find(BuoyWaveMotion.VisualChildName);
            if(m_visual==null) {
                if(m_config.flotation.enabled||m_config.lantern.enabled) throw new InvalidOperationException("Flotation/lantern requires the realistic buoy's '"+BuoyWaveMotion.VisualChildName+"' child. Disable both for other models.");
                m_visual=m_target.transform;
            }
            Vector3 aim=m_target.transform.position+new Vector3(0,Mathf.Max(.3f,bounds.center.y-m_target.transform.position.y),0);
            m_aimOffset=m_visual.InverseTransformPoint(aim);m_meanAim=aim;
            m_targetStart=m_target.transform.position;m_targetRotation=m_target.transform.rotation;
            if(m_config.flotation.enabled) {
                if(ocean.waterMask!=null) throw new InvalidOperationException("HDRP 14 CPU flotation does not account for water masks. Use an unmasked ocean for this pilot.");
                if(m_target.GetComponent<BuoyWaveMotion>()!=null) throw new InvalidOperationException("The target already has a flotation controller; avoid concurrent controllers.");
                m_waveMotion=m_target.AddComponent<BuoyWaveMotion>();m_ownsWaveMotion=true;
                m_waveMotion.Configure(ocean,m_visual,captureCamera,m_config.flotation);
            }
            if(m_config.lantern.enabled||m_visual.name==BuoyWaveMotion.VisualChildName) {
                if(m_target.GetComponent<BuoyLanternFlash>()!=null) throw new InvalidOperationException("The target already has a lantern controller.");
                m_lantern=m_target.AddComponent<BuoyLanternFlash>();
                m_lantern.Configure(m_visual,captureCamera,m_config.lantern);
            }
            m_lastRenderRealtime=Time.realtimeSinceStartup;
            RenderPipelineManager.endContextRendering+=OnEndRendering;
            Debug.Log("[Dataset] Starting "+Expected+" images. Output: "+OutputDirectory);

            foreach(var condition in m_config.Conditions()) {
                m_condition=condition;
                AssertTargetStatic();ApplyCondition(condition);
                int readyFrame=m_renderedFrames+m_config.settleRenderedFrames;
                SetStatus("settling");
                while(m_renderedFrames<readyFrame) {CheckRenderHealth();yield return null;}
                for(m_sample=0;m_sample<m_config.samplesPerCondition;m_sample++) {
                    if(m_sample>0) {
                        readyFrame=m_renderedFrames+Mathf.CeilToInt(m_config.sampleIntervalSeconds*m_config.simulationFps);
                        while(m_renderedFrames<readyFrame) {CheckRenderHealth();yield return null;}
                    }
                    AssertTargetStatic();m_captureError=null;m_captureArmed=true;
                    if(m_maskPass!=null) {m_maskPass.armed=true;m_maskRequestedRealtime=Time.realtimeSinceStartup;}
                    SetStatus("capturing");
                    while(m_captureArmed) {CheckRenderHealth();yield return null;}
                    if(m_captureError!=null) throw m_captureError;
                }
            }
            if(Captured!=Expected) throw new InvalidOperationException("Incomplete campaign: "+Captured+" / "+Expected);
            VerifyPairs();m_annotations?.FinalizeIndex();WriteGallery();
            m_runStatus.capturesComplete=true;
            if(m_ownsScenario&&m_config.stopOwnedScenarioOnCompletion) {
                SetStatus("stopping_owned_scenario");
                var stop=StopOwnedScenario();float deadline=Time.realtimeSinceStartup+m_config.objectTimeoutSeconds;
                while(!stop.IsCompleted&&Time.realtimeSinceStartup<=deadline) yield return null;
                if(!stop.IsCompleted||stop.IsFaulted) {
                    m_runStatus.scenarioCleanupWarning=!stop.IsCompleted?"All captures saved, but stopping the owned scenario timed out. Inspect LOTUSim before restarting.":stop.Exception.ToString();
                    Debug.LogWarning("[Dataset] Capture complete; cleanup unconfirmed: "+m_runStatus.scenarioCleanupWarning);
                    SetStatus("complete_cleanup_unconfirmed");m_running=false;
                    RenderPipelineManager.endContextRendering-=OnEndRendering;
                    yield break;
                }
            }
            SetStatus("complete");m_running=false;
            RenderPipelineManager.endContextRendering-=OnEndRendering;
            Debug.Log("[Dataset] COMPLETE: "+Captured+" / "+Expected+". Open "+Path.Combine(OutputDirectory,"index.html"));
        }

        void SetupRendering()
        {
            m_previousCaptureFps=Time.captureFramerate;m_previousPipeline=QualitySettings.renderPipeline;
            QualitySettings.renderPipeline=waterPipeline;Time.captureFramerate=m_config.simulationFps;m_settingsChanged=true;
            m_previousTarget=captureCamera.targetTexture;
            m_targetTexture=new RenderTexture(m_config.width,m_config.height,24,RenderTextureFormat.ARGB32,RenderTextureReadWrite.sRGB){name="Dataset RGB",antiAliasing=1,useDynamicScale=false};
            m_targetTexture.Create();m_pixels=new Texture2D(m_config.width,m_config.height,TextureFormat.RGB24,false,false);
            captureCamera.targetTexture=m_targetTexture;captureCamera.fieldOfView=m_config.verticalFovDeg;
            captureCamera.aspect=(float)m_config.width/m_config.height;captureCamera.nearClipPlane=.05f;captureCamera.farClipPlane=10000;
            captureCamera.allowDynamicResolution=false;captureCamera.enabled=true;
            var hd=captureCamera.GetComponent<HDAdditionalCameraData>()??captureCamera.gameObject.AddComponent<HDAdditionalCameraData>();
            hd.antialiasing=HDAdditionalCameraData.AntialiasingMode.SubpixelMorphologicalAntiAliasing;hd.xrRendering=false;
            hd.volumeLayerMask=~0;hd.clearColorMode=HDAdditionalCameraData.ClearColorMode.Sky;
            if(m_config.annotations.enabled) {
                hd.customRenderingSettings=true;
                hd.renderingPathCustomFrameSettings.SetEnabled(FrameSettingsField.CustomPass,true);
                hd.renderingPathCustomFrameSettingsOverrideMask.mask[(uint)FrameSettingsField.CustomPass]=true;
            }
            m_profile=environmentVolume.profile;
            Override<WaterRendering>().enable.Override(true);
            var visual=Override<VisualEnvironment>();visual.skyType.Override((int)SkyType.PhysicallyBased);visual.skyAmbientMode.Override(SkyAmbientMode.Dynamic);
            var sky=Override<PhysicallyBasedSky>();sky.active=true;sky.updateMode.Override(EnvironmentUpdateMode.Realtime);sky.updatePeriod.Override(0);
            Override<Exposure>().mode.Override(ExposureMode.Fixed);
            Override<MotionBlur>().intensity.Override(0);
            Override<DepthOfField>().focusMode.Override(DepthOfFieldMode.Off);
            ocean.cpuSimulation=true;ocean.cpuFullResolution=true;ocean.cpuEvaluateRipples=false;ocean.timeMultiplier=1;
            // Optical attenuation is applied by HDRP along the water path. Do
            // not tint buoy materials or substitute an object-height color rule.
            ocean.absorptionDistance=m_config.waterOptics.absorptionDistanceM;
            ocean.maxRefractionDistance=m_config.waterOptics.maxRefractionDistanceM;
            ocean.refractionColor=m_config.waterOptics.refractionColor;ocean.scatteringColor=m_config.waterOptics.scatteringColor;
            ocean.underWater=true;ocean.absorbtionDistanceMultiplier=1;
            sun.enabled=true;sun.shadows=LightShadows.Soft;RenderSettings.sun=sun;
        }

        T Override<T>() where T:VolumeComponent
        {
            if(!m_profile.TryGet<T>(out var component)) component=m_profile.Add<T>();
            component.active=true;
            return component;
        }

        void ApplyCondition(DatasetCondition condition)
        {
            // Position stays fixed at the mean orbit point. Synthetic camera
            // sway is a bounded local rotation, not a moving observer vessel.
            Vector3 aim=m_meanAim;
            captureCamera.transform.SetPositionAndRotation(aim+DatasetCampaignConfig.OrbitOffset(condition.distanceM,condition.azimuthDeg,condition.elevationDeg),Quaternion.identity);
            captureCamera.transform.LookAt(aim,Vector3.up);
            m_nominalCameraPosition=captureCamera.transform.position;m_nominalCameraRotation=captureCamera.transform.rotation;
            m_cameraMotionStartTime=Time.timeAsDouble;m_cameraPoseReady=true;
            var sea=condition.sea;
            ocean.largeWindSpeed=sea.windKmh;ocean.largeWindOrientationValue=sea.directionDeg;ocean.largeChaos=.65f;
            ocean.largeBand0Multiplier=sea.band0;ocean.largeBand1Multiplier=sea.band1;
            ocean.largeBand0FadeToggle=false;ocean.largeBand1FadeToggle=false;
            ocean.ripples=true;ocean.ripplesWindSpeed=sea.ripplesKmh;ocean.ripplesWindOrientationValue=sea.directionDeg;
            ocean.simulationFoamAmount=sea.foam;ocean.repetitionSize=sea.patchSizeM;
            var light=condition.light;
            Vector3 toSun=DatasetCampaignConfig.OrbitOffset(1,condition.azimuthDeg+light.relativeBearingDeg,light.elevationDeg);
            sun.transform.rotation=Quaternion.LookRotation(-toSun,Vector3.up);
            var hd=sun.GetComponent<HDAdditionalLightData>()??sun.gameObject.AddComponent<HDAdditionalLightData>();
            hd.SetIntensity(light.intensityLux,LightUnit.Lux);sun.useColorTemperature=true;sun.colorTemperature=light.temperatureKelvin;
            Override<Exposure>().fixedExposure.Override(light.exposureEV100);
        }

        void OnSourcePose(VesselPositionArrayMsg message)
        {
            if(m_config==null||message.vessels==null) return;
            m_poseMessages++;m_lastPoseNames=message.vessels.Select(v=>v.vessel_name).ToArray();
            if(!message.vessels.Any(v=>v.vessel_name==m_config.targetName)) return;
            m_targetPoseMessages++;
            m_receivedPose=true;m_rosSec=message.header.stamp.sec;m_rosNanosec=message.header.stamp.nanosec;
        }

        string TargetReadiness()
        {
            bool exists=m_target!=null;
            int renderers=exists?m_target.GetComponentsInChildren<MeshRenderer>().Length:0;
            return "Target '"+m_config.targetName+"' is not ready: Unity object="+exists+", renderers="+renderers+
                ", pose messages="+m_poseMessages+", target poses="+m_targetPoseMessages+
                ", latest ROS objects=["+string.Join(", ",m_lastPoseNames)+"]. "+
                (m_poseMessages>0&&m_targetPoseMessages==0?"ROS is receiving data, but LOTUSim is not publishing this target.":"Check the prefab creation and ROS pose publisher.");
        }

        void OnEndRendering(ScriptableRenderContext context,List<Camera> cameras)
        {
            if(!m_running||!cameras.Contains(captureCamera)) return;
            m_renderedFrames++;m_lastRenderRealtime=Time.realtimeSinceStartup;
            if(!m_captureArmed) return;
            // Never save an RGB/pose pair if the current water query failed or
            // refers to a different frame. The health check bounds this wait.
            if(m_waveMotion!=null&&(!m_waveMotion.HasValidSample||m_waveMotion.SampleUnityFrame!=Time.frameCount)) return;
            if(m_lantern!=null&&m_lantern.SampleUnityFrame!=Time.frameCount) return;
            if(m_cameraMotionFrame!=Time.frameCount) return;
            if(m_maskPass!=null&&m_maskPass.Frame!=Time.frameCount) {m_maskPass.armed=true;return;}
            try {
                AssertTargetStatic();
                string id="c"+m_condition.index.ToString("D4")+"_s"+m_sample.ToString("D2");
                var info=FrameMetadata(id);
                RenderTexture previous=RenderTexture.active;
                try {RenderTexture.active=m_targetTexture;m_pixels.ReadPixels(new Rect(0,0,m_config.width,m_config.height),0,0,false);m_pixels.Apply(false,false);}
                finally {RenderTexture.active=previous;}
                byte[] png=m_pixels.EncodeToPNG();
                if(png==null||png.Length<100) throw new IOException("Invalid or empty PNG.");
                if(m_annotations!=null) {
                    var annotation=m_annotations.Export(id,m_pixels,m_maskPass.Visible.rt,m_maskPass.Amodal.rt,Time.frameCount);
                    info.annotationStatus="geometry_mask_generated";info.annotationFile="annotations/"+id+".json";
                    info.visibleMaskFile=annotation.maskFile;info.annotationOverlayFile=annotation.overlayFile;
                }
                AtomicWrite(Path.Combine(OutputDirectory,"rgb",id+".png"),png);
                AtomicWrite(Path.Combine(OutputDirectory,"metadata",id+".json"),JsonUtility.ToJson(info,true));
                m_files.Add(id);Captured++;WriteStatus();
                if(Captured==1||Captured%24==0) Debug.Log("[Dataset] "+Captured+" / "+Expected);
            }
            catch(Exception exception) {m_captureError=exception;}
            finally {m_captureArmed=false;}
        }

        FrameInfo FrameMetadata(string id)
        {
            // HDRP uses a camera-specific stack. The global stack can still hold
            // defaults (e.g. EV=0) after this camera has rendered at EV=13.
            var exposure=HDCamera.GetOrCreate(captureCamera).volumeStack.GetComponent<Exposure>();
            var hd=sun.GetComponent<HDAdditionalLightData>();
            var info=new FrameInfo{imageId=id,imageFile="rgb/"+id+".png",utc=DateTime.UtcNow.ToString("O"),objectSource=m_config.objectSource.ToString(),
                instance=m_config.targetName,model=m_config.modelAddress,category=m_config.category,
                displayName=DatasetOverlayLabel.DisplayName(m_config.category,m_config.annotations.displayName),classId=m_config.classId,conditionIndex=m_condition.index,sampleIndex=m_sample,
                seed=m_config.seed,width=m_targetTexture.width,height=m_targetTexture.height,unityFrame=Time.frameCount,renderedFrame=m_renderedFrames,
                simulationTimeSeconds=Time.time,waterTimeMultiplier=ocean.timeMultiplier,verticalFovDeg=captureCamera.fieldOfView,
                distanceRequestedM=m_condition.distanceM,distanceAppliedM=Vector3.Distance(captureCamera.transform.position,m_visual.TransformPoint(m_aimOffset)),
                azimuthDeg=m_condition.azimuthDeg,elevationDeg=m_condition.elevationDeg,cameraPosition=captureCamera.transform.position,cameraRotation=captureCamera.transform.rotation,
                targetPosition=m_visual.position,targetRotation=m_visual.rotation,aimPoint=m_visual.TransformPoint(m_aimOffset),
                anchorPosition=m_target.transform.position,anchorRotation=m_target.transform.rotation,
                visualFlotationEnabled=m_waveMotion!=null,flotationRequested=m_config.flotation,
                waterOpticsRequested=m_config.waterOptics,
                waterOpticsApplied=new DatasetWaterOpticsSettings{absorptionDistanceM=ocean.absorptionDistance,maxRefractionDistanceM=ocean.maxRefractionDistance,
                    refractionColor=ocean.refractionColor,scatteringColor=ocean.scatteringColor},
                lanternRequested=m_config.lantern,lanternOn=m_lantern!=null&&m_lantern.Level>0,
                lanternLevel=m_lantern==null?0:m_lantern.Level,lanternPhaseSeconds=m_lantern==null?0:m_lantern.PhaseSeconds,
                lanternLightLumens=m_lantern==null?0:m_lantern.AppliedLightLumens,lanternSampleUnityFrame=m_lantern==null?-1:m_lantern.SampleUnityFrame,
                cameraMotionModel=m_config.cameraMotion.enabled?"synthetic_small_angle_sway":"fixed",cameraMotionRequested=m_config.cameraMotion,
                cameraNominalPosition=m_nominalCameraPosition,cameraNominalRotation=m_nominalCameraRotation,
                cameraPitchDeg=m_cameraPitchRoll.x,cameraRollDeg=m_cameraPitchRoll.y,cameraMotionElapsedSeconds=m_cameraMotionElapsed,
                cameraMotionSeaScale=m_condition.sea.cameraMotionScale,cameraMotionSampleUnityFrame=m_cameraMotionFrame,
                sunRayDirection=sun.transform.forward,sunAppliedLux=hd.intensity,exposureAppliedEV100=exposure==null?Override<Exposure>().fixedExposure.value:exposure.fixedExposure.value,
                rosPoseStampAvailable=m_receivedPose,rosStampSec=m_rosSec,rosStampNanosec=m_rosNanosec,
                viewMatrix=Matrix(captureCamera.worldToCameraMatrix),projectionMatrix=Matrix(captureCamera.projectionMatrix),gpuProjectionMatrix=Matrix(GL.GetGPUProjectionMatrix(captureCamera.projectionMatrix,true)),
                seaRequested=m_condition.sea,lightRequested=m_condition.light,
                seaApplied=new DatasetSeaPreset{name=m_condition.sea.name,windKmh=ocean.largeWindSpeed,band0=ocean.largeBand0Multiplier,band1=ocean.largeBand1Multiplier,
                    ripplesKmh=ocean.ripplesWindSpeed,foam=ocean.simulationFoamAmount,directionDeg=ocean.largeWindOrientationValue,patchSizeM=ocean.repetitionSize,
                    cameraMotionScale=m_condition.sea.cameraMotionScale}};
            info.waterQueryIncludesRipples=ocean.cpuEvaluateRipples;
            if(m_waveMotion!=null) {
                info.motionModel="unity_hdrp_moored_kinematic_5_probe";
                info.waterQueryAvailable=m_waveMotion.HasValidSample;info.waterHeightAtTargetM=m_waveMotion.CenterWaterHeightM;
                info.flotationSampleUnityFrame=m_waveMotion.SampleUnityFrame;
                info.flotationMeanWaterHeightM=m_waveMotion.MeanWaterHeightM;info.flotationHeaveM=m_waveMotion.HeaveM;
                info.flotationTiltDeg=m_waveMotion.AppliedTiltDeg;info.flotationSurfaceNormal=m_waveMotion.SurfaceNormal;
                info.flotationMaxQueryErrorM=m_waveMotion.MaxQueryErrorM;
                return info;
            }
            var query=new WaterSearchParameters{targetPosition=m_target.transform.position,startPosition=m_target.transform.position,error=.01f,maxIterations=8};
            info.waterQueryAvailable=ocean.FindWaterSurfaceHeight(query,out var result);
            if(info.waterQueryAvailable) info.waterHeightAtTargetM=result.height;
            return info;
        }

        static float[] Matrix(Matrix4x4 matrix) {var result=new float[16];for(int i=0;i<16;i++) result[i]=matrix[i];return result;}

        void AssertTargetStatic()
        {
            if(m_target==null) throw new InvalidOperationException("Target disappeared during the campaign.");
            if(Vector3.Distance(m_target.transform.position,m_targetStart)>.001f||Quaternion.Angle(m_target.transform.rotation,m_targetRotation)>.1f)
                throw new InvalidOperationException("This pilot requires a fixed ROS anchor. Its source pose changed during capture; visual wave flotation is allowed.");
        }
        void CheckRenderHealth()
        {
            if(m_captureError!=null) throw m_captureError;
            if(m_maskPass!=null&&m_maskPass.Error!=null) throw new InvalidOperationException(m_maskPass.Error);
            if(m_captureArmed&&m_maskPass!=null&&Time.realtimeSinceStartup-m_maskRequestedRealtime>m_config.renderTimeoutSeconds)
                throw new TimeoutException("Annotation pass did not produce a valid mask for the capture camera.");
            if(m_target==null) throw new InvalidOperationException("Target disappeared.");
            if(Time.realtimeSinceStartup-m_lastRenderRealtime>m_config.renderTimeoutSeconds)
                throw new TimeoutException("Dataset camera stopped rendering. Check Play/Pause and HDRP errors.");
            if(m_waveMotion!=null&&Time.realtimeSinceStartup-m_waveMotion.LastValidRealtime>m_config.renderTimeoutSeconds)
                throw new TimeoutException("Visual flotation has no valid water sample: "+m_waveMotion.LastQueryFailure);
            if(m_lantern!=null&&Time.realtimeSinceStartup-m_lantern.LastUpdatedRealtime>m_config.renderTimeoutSeconds)
                throw new TimeoutException("Buoy lantern stopped updating. Check its lens renderer.");
            if(m_config.objectSource==DatasetObjectSource.Lotusim&&m_ros.HasConnectionError)
                throw new InvalidOperationException("ROS connection lost; campaign interrupted.");
        }

        Task StopOwnedScenario()
        {
            if(m_stopTask==null) m_stopTask=StopOwnedScenarioOnce();
            return m_stopTask;
        }
        async Task StopOwnedScenarioOnce()
        {
            if(!m_ownsScenario||m_ros==null) return;
            string service="/"+m_config.rosNamespace.Trim('/')+"/stop_scenario";
            MessageRegistry.Register(DatasetTriggerRequest.RosName,DatasetTriggerRequest.Deserialize);
            MessageRegistry.Register(TriggerResponse.k_RosMessageName,TriggerResponse.Deserialize,MessageSubtopic.Response);
            m_ros.RegisterRosService<DatasetTriggerRequest,TriggerResponse>(service);
            var response=await m_ros.SendServiceMessage<TriggerResponse>(service,new DatasetTriggerRequest());
            if(!response.success) throw new InvalidOperationException("Could not stop the owned scenario: "+response.message);
            m_ownsScenario=false;
            if(m_runStatus!=null) {
                m_runStatus.scenarioStopConfirmed=true;
                if(Status=="complete_cleanup_unconfirmed") {Status="complete";m_runStatus.scenarioCleanupWarning="";}
            }
            WriteStatus();
        }

        void VerifyPairs()
        {
            foreach(string id in m_files) if(!File.Exists(Path.Combine(OutputDirectory,"rgb",id+".png"))||!File.Exists(Path.Combine(OutputDirectory,"metadata",id+".json")))
                throw new IOException("Missing image/metadata pair: "+id);
            if(m_annotations!=null) {
                if(m_annotations.Count!=Captured) throw new IOException("RGB/annotation count mismatch.");
                foreach(string id in m_files) foreach(string file in new[]{"masks/"+id+".png","amodal/"+id+".png","overlays/"+id+".png","labels/"+id+".txt","annotations/"+id+".json"})
                    if(!File.Exists(Path.Combine(OutputDirectory,file))) throw new IOException("Missing annotation file: "+file);
            }
        }
        void WriteGallery()
        {
            bool annotated=m_annotations!=null;
            var html=new System.Text.StringBuilder("<!doctype html><html lang='fr'><meta charset='utf-8'><title>LOTUSim — campagne</title><style>body{background:#17212b;color:#eee;font:16px system-ui;margin:24px}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}img{width:100%}a{color:#8dd7ff}figure{margin:0}</style><h1>Campagne — "+Captured+" images</h1><p>"+(annotated?"Boîte verte, contour jaune, nom de classe au-dessus. Annotation géométrique ; l’eau est traitée comme un occultant. <a href='annotations.coco.json'>COCO</a>":"RGB sans annotation.")+"</p><main>");
            foreach(string id in m_files) html.Append("<figure><a href='"+(annotated?"overlays/":"rgb/")+id+".png'><img loading='lazy' src='"+(annotated?"overlays/":"rgb/")+id+".png'></a><figcaption>"+id+" · <a href='rgb/"+id+".png'>RGB</a> · <a href='metadata/"+id+".json'>paramètres</a>"+(annotated?" · <a href='masks/"+id+".png'>masque</a> · <a href='annotations/"+id+".json'>annotation</a>":"")+"</figcaption></figure>");
            html.Append("</main></html>");AtomicWrite(Path.Combine(OutputDirectory,"index.html"),html.ToString());
        }
        void SetStatus(string status) {Status=status;WriteStatus();}
        void WriteStatus()
        {
            if(m_runStatus==null) return;
            m_runStatus.status=Status;m_runStatus.captured=Captured;m_runStatus.updatedUtc=DateTime.UtcNow.ToString("O");
            m_runStatus.scenarioOwned=m_ownsScenario;m_runStatus.images=m_files.ToArray();
            if(m_annotations!=null) {
                m_runStatus.annotatedFrames=m_annotations.Count;m_runStatus.annotationBoxes=m_annotations.Boxes;
                m_runStatus.annotationsProduced=m_annotations.Count>0;
            }
            m_runStatus.poseMessages=m_poseMessages;m_runStatus.targetPoseMessages=m_targetPoseMessages;
            m_runStatus.lastPoseNames=string.Join(", ",m_lastPoseNames);
            if(m_config!=null) m_runStatus.targetReadiness=TargetReadiness();
            AtomicWrite(Path.Combine(OutputDirectory,"status.json"),JsonUtility.ToJson(m_runStatus,true));
        }
        static void AtomicWrite(string path,string content) => AtomicWrite(path,System.Text.Encoding.UTF8.GetBytes(content));
        static void AtomicWrite(string path,byte[] content)
        {
            string temporary=path+".partial";File.WriteAllBytes(temporary,content);
            if(File.Exists(path)) File.Replace(temporary,path,null);else File.Move(temporary,path);
        }
        void Fail(Exception exception)
        {
            m_running=false;m_captureArmed=false;Status="failed";
            if(m_runStatus!=null) {m_runStatus.error=exception.Message;m_runStatus.errorDetails=exception.ToString();try {m_annotations?.FinalizeIndex();WriteStatus();WriteGallery();} catch(Exception io) {Debug.LogWarning("[Dataset] Could not finalize report: "+io.Message);}}
            RenderPipelineManager.endContextRendering-=OnEndRendering;
            Debug.LogError("[Dataset] FAILED: "+exception+". Completed pairs remain in "+OutputDirectory);
            if(m_ownsScenario&&m_config.stopOwnedScenarioOnCompletion) ObserveStop();
        }
        async void ObserveStop() {try {await StopOwnedScenario();} catch(Exception e) {Debug.LogWarning("[Dataset] Owned scenario cleanup unconfirmed: "+e.Message);}}

        void OnDisable()
        {
            RenderPipelineManager.endContextRendering-=OnEndRendering;
            if(m_running) {
                m_running=false;m_captureArmed=false;Status="cancelled";
                try {m_annotations?.FinalizeIndex();WriteStatus();WriteGallery();} catch(Exception e) {Debug.LogWarning("[Dataset] Cancel report: "+e.Message);}
                if(m_ownsScenario&&m_config!=null&&m_config.stopOwnedScenarioOnCompletion) ObserveStop();
            }
            if(m_settingsChanged) {QualitySettings.renderPipeline=m_previousPipeline;Time.captureFramerate=m_previousCaptureFps;m_settingsChanged=false;}
            if(m_ownsWaveMotion&&m_waveMotion!=null) {m_waveMotion.enabled=false;Destroy(m_waveMotion);m_waveMotion=null;}
            if(m_lantern!=null) {m_lantern.enabled=false;Destroy(m_lantern);m_lantern=null;}
            if(m_maskRoot!=null) Destroy(m_maskRoot);
            if(m_annotations!=null) {m_annotations.Dispose();m_annotations=null;}
            if(captureCamera!=null) captureCamera.targetTexture=m_previousTarget;
            if(m_targetTexture!=null) {m_targetTexture.Release();Destroy(m_targetTexture);m_targetTexture=null;}
            if(m_pixels!=null) Destroy(m_pixels);
            if(m_localObject!=null) Destroy(m_localObject);
            if(m_config!=null) Destroy(m_config);
            // Do not Unsubscribe: this endpoint lacks remove_subscriber. ROS lifetime is unchanged.
        }
    }
}
