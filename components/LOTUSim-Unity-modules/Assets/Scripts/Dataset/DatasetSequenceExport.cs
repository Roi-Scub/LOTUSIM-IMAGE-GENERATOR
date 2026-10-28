using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;

namespace Lotusim.Dataset
{
    public sealed class DatasetSequenceActor
    {
        public DatasetEncounter encounter;
        public DatasetEncounterClass definition;
        public GameObject root;
        public DatasetMaskTarget mask;
        public Transform visual;
        public BuoyWaveMotion flotation;
        public BuoyLanternFlash lantern;
        public MarineVesselWaveMotion marineMotion;
        public DatasetAircraftLights lights;
        public DatasetAssetLights assetLights;
        public DatasetMeshAnimation meshAnimation;
        public DatasetAerialResponse aerialResponse;
        public Vector3 sourceVelocity;
        public Pose sourcePose;
        public ulong sourceEntity;
    }
    [Serializable] public sealed class DatasetSequenceObjectState
    {
        public string instance,category,motionModel,modelName;
        public string plannedFlightMode;
        public float plannedSpeedKmh,plannedYawRateDegS;
        public int trackId,visiblePixels,flotationSampleUnityFrame=-1;
        public int amodalPixelsInFrame;
        public float visiblePercent,occludedPercent;
        public string recognitionStatus="NR",recognitionReason="not_measured";
        public Vector3 position,velocity;
        public Quaternion rotation;
        public float cameraDistanceM,lanternLevel;
        public string flotationModel;
        public float vesselHeaveM,vesselRollDeg,vesselPitchDeg;
        public bool syntheticThermalPrior;
        public float assumedSurfaceTemperatureC,assumedEmissivity;
        public DatasetAircraftLightState[] lights=Array.Empty<DatasetAircraftLightState>();
        public int meshAnimationFrame=-1;
        public string animationModel,visualFlightResponse;
        public Vector3 sourceRootPosition;
        public Quaternion sourceRootRotation;
        public ulong sourceEntity;
    }
    [Serializable] public sealed class DatasetSequenceFrame
    {
        public string schema="lotusim-unity-sequence-frame-1",sequenceId,imageId,policy="nearest_depth_water_is_opaque";
        public int imageIndex,seed,width,height,unityFrame,simulationFrame;
        public float sequenceTimeSeconds,unityWaterTimeSeconds;
        public string motionSource="Unity kinematic; no live ROS",northAxis="Unity +Z",eastAxis="Unity +X";
        public Vector3 cameraPosition,cameraNominalPosition,waterNormal;
        public Quaternion cameraRotation;
        public float cameraRollDeg,cameraPitchDeg,cameraHeaveM;
        public bool waterQueryValid,cameraWaterSampleFromPreviousRender=true;
        public int cameraWaterSampleFrame;
        public float[] viewMatrix,projectionMatrix;
        public DatasetSeaPreset sea;
        public DatasetLightPreset light;
        public int lightingPhaseIndex;
        public string lightingTimeOfDay;
        public DatasetFrameAnnotation[] annotations;
        public DatasetSequenceObjectState[] activeObjects;
        public string lotusimRunId,lotusimPlanId;
        public double lotusimWorldTimeSeconds;
        public int rosConnectionInstanceId;
        public Vector3 observerRootPosition;
        public Quaternion observerRootRotation;
        public string cameraMount;
        public float observerHeadingDeg;
        public Vector3 cameraLocalMountPosition,observerVisualPosition;
        public Quaternion cameraLocalMountRotation,observerVisualRotation;
        public float observerRollDeg,observerPitchDeg;
        public DatasetSensorFrame[] sensors;
        public string trafficPlanSha256,trafficPlannerSha256;
        public bool hasTrafficWeather,seaWindIsSpectrumProxy;
        public float localWindMps,requestedSwellHeightM;
        public DatasetManualImageMetadata manualCampaign;
        public string observerExclusionFile;
        public int observerExclusionUnityFrame=-1;
    }
    public sealed partial class DatasetSequenceExport : IDisposable
    {
        [Serializable] sealed class CocoAnnotation {
            public int id,image_id,category_id,track_id,area,iscrowd=0;public string instance;public int[] bbox;public DatasetCocoRle segmentation;
            public float visible_percent,occluded_percent,rgb_local_contrast;public string recognition_status,recognition_reason;
        }
        [Serializable] sealed class Coco {
            public string annotation_policy="nearest_depth_water_is_opaque",sequence_id;
            public List<DatasetCocoImage> images=new List<DatasetCocoImage>();public List<CocoAnnotation> annotations=new List<CocoAnnotation>();public DatasetCocoCategory[] categories;
        }
        [Serializable] sealed class ClassMap {public DatasetClassMap[] classes;}
        [Serializable] sealed class ObserverExclusionManifest {
            public string schema="lotusim-observer-exclusion-1",coordinateSystem="image_pixels_top_left",maskDirectory="observer-exclusion";
            public string source="unity_observer_visible_depth";
            public bool observerOnly=true,rgbSameRender=true,observerExclusionOnlyScope=true;
            public string maskMeaning="Visible ownship pixels only; no target categories, poses or annotations are inference input.";
            public int foregroundValue=255,width,height;
            public List<ObserverExclusionFrame> frames=new List<ObserverExclusionFrame>();
        }
        [Serializable] sealed class ObserverExclusionFrame {
            public string imageFile,maskFile,rgbSha256,maskSha256;
            public int unityFrame;
        }
        readonly string output;
        readonly DatasetSequenceConfig config;
        readonly Texture2D visible,amodal,overlay,maskPng;
        readonly Coco coco;
        readonly List<string> review=new List<string>();
        readonly ObserverExclusionManifest observerExclusionManifest;
        public int Count=>coco.images.Count;
        public int Boxes=>coco.annotations.Count;
        public DatasetSequenceExport(string directory,string sequenceId,DatasetSequenceConfig config)
        {
            output=directory;this.config=config;
            observerExclusionManifest=new ObserverExclusionManifest{width=config.width,height=config.height};
            foreach(string dir in new[]{"rgb","masks","amodal","overlays","annotations","labels","labels-recognizable"}) Directory.CreateDirectory(Path.Combine(output,dir));
            visible=new Texture2D(config.width,config.height,TextureFormat.RGB24,false,true);
            amodal=new Texture2D(config.width,config.height,TextureFormat.RGB24,false,true);overlay=new Texture2D(config.width,config.height,TextureFormat.RGB24,false,false);
            maskPng=new Texture2D(config.width,config.height,TextureFormat.R8,false,true);
            InitializeSensors();
            coco=new Coco{sequence_id=sequenceId,categories=config.classes.Select(c=>new DatasetCocoCategory{id=c.classId,name=c.category,displayName=c.displayName}).ToArray()};
            Atomic(Path.Combine(output,"classes.txt"),string.Join("\n",config.classes.Select(c=>c.category))+"\n");
            Atomic(Path.Combine(output,"class-map.json"),JsonUtility.ToJson(new ClassMap{classes=config.classes.Select((c,i)=>new DatasetClassMap{yolo_index=i,coco_category_id=c.classId,name=c.category,displayName=c.displayName}).ToArray()},true));
            Atomic(Path.Combine(output,"recognition-policy.json"),JsonUtility.ToJson(config.annotations.recognition??new DatasetRecognitionSettings(),true));
        }
        public void Export(Texture2D rgb,DatasetMultiInstanceMaskPass pass,DatasetSequenceActor[] actors,DatasetSequenceFrame frame,DatasetSpectralPass spectral=null)
        {
            var annotations=new List<DatasetFrameAnnotation>();var cocoObjects=new List<CocoAnnotation>();var labels=new StringBuilder();var recognizableLabels=new StringBuilder();
            var cleanRgb=rgb.GetPixels32();var pixels=(Color32[])cleanRgb.Clone();int imageId=Count+1;string id=frame.imageId;
            // Encode once: the byte hash identifies the exact raw PNG paired
            // with the observer-only mask, not any target annotation file.
            var rgbBytes=rgb.EncodeToPNG();
            var observerExclusion=ExportObserverExclusion(pass,frame,Hash(rgbBytes));
            Directory.CreateDirectory(Path.Combine(output,"masks",id));Directory.CreateDirectory(Path.Combine(output,"amodal",id));
            for(int slot=0;slot<actors.Length;slot++) {
                var actor=actors[slot];Read(pass.Visible[slot].rt,visible);Read(pass.Amodal[slot].rt,amodal);
                var mask=visible.GetPixels32();var full=amodal.GetPixels32();var stats=DatasetAnnotationExport.Measure(mask,config.width,config.height);var total=DatasetAnnotationExport.Measure(full,config.width,config.height);
                for(int i=0;i<mask.Length;i++) if(mask[i].r>=128&&full[i].r<128) throw new InvalidOperationException("Sequence mask alignment invalid.");
                string suffix=id+"/"+actor.encounter.instance+".png";
                Atomic(Path.Combine(output,"masks",suffix),EncodeMask(mask));Atomic(Path.Combine(output,"amodal",suffix),EncodeMask(full));
                var annotation=new DatasetFrameAnnotation{instance=actor.encounter.instance,trackId=actor.encounter.trackId,category=actor.definition.category,displayName=actor.definition.displayName,
                    categoryId=actor.definition.classId,yoloClassIndex=actor.encounter.classIndex,unityFrame=frame.unityFrame,visiblePixels=stats.area,amodalPixelsInFrame=total.area,
                    geometricVisibleFractionInFrame=total.area==0?0:(float)stats.area/total.area,bbox=stats.bbox,annotationPresent=stats.area>0,truncatedInFrame=total.touchesImageEdge,
                    maskFile="masks/"+suffix,amodalMaskFile="amodal/"+suffix,overlayFile="overlays/"+id+".png"};
                annotation.needsManualReview=stats.area<config.annotations.reviewMinVisiblePixels||stats.bbox[2]<config.annotations.reviewMinBoxSidePixels||stats.bbox[3]<config.annotations.reviewMinBoxSidePixels;
                annotation.reviewReason=annotation.needsManualReview?"small_geometric_target":"";
                DatasetRecognition.Assess(annotation,total,cleanRgb,mask,config.width,config.height,config.annotations.recognition);
                var state=frame.activeObjects[slot];state.visiblePixels=stats.area;state.amodalPixelsInFrame=total.area;state.visiblePercent=annotation.visiblePercent;state.occludedPercent=annotation.occludedPercent;
                state.recognitionStatus=annotation.recognitionStatus;state.recognitionReason=annotation.recognitionReason;
                if(stats.area==0)continue; // Hidden/out-of-frame: retain status, never invent a visible box.
                if(annotation.needsManualReview) review.Add(id+"\t"+actor.encounter.instance);
                annotations.Add(annotation);labels.Append(DatasetAnnotationExport.Yolo(stats.bbox,config.width,config.height,actor.encounter.classIndex));
                if(annotation.recognitionStatus=="R")recognizableLabels.Append(DatasetAnnotationExport.Yolo(stats.bbox,config.width,config.height,actor.encounter.classIndex));
                DatasetAnnotationExport.PaintOverlay(pixels,mask,stats,config.width,config.height,DatasetRecognition.Color(annotation.recognitionStatus));
                cocoObjects.Add(new CocoAnnotation{image_id=imageId,category_id=actor.definition.classId,track_id=actor.encounter.trackId,instance=actor.encounter.instance,area=stats.area,bbox=stats.bbox,
                    visible_percent=annotation.visiblePercent,occluded_percent=annotation.occludedPercent,rgb_local_contrast=annotation.rgbLocalContrast,recognition_status=annotation.recognitionStatus,recognition_reason=annotation.recognitionReason,
                    segmentation=new DatasetCocoRle{size=new[]{config.height,config.width},counts=DatasetAnnotationExport.Rle(mask,config.width,config.height)}});
            }
            var labelPlates=new List<int[]>();
            foreach(var annotation in annotations) {
                annotation.overlayLabelBox=DatasetOverlayLabel.Paint(pixels,config.width,config.height,
                    new DatasetMaskStats{area=annotation.visiblePixels,bbox=annotation.bbox},DatasetRecognition.Label(annotation),labelPlates,DatasetRecognition.Color(annotation.recognitionStatus));
                labelPlates.Add(annotation.overlayLabelBox);
            }
            overlay.SetPixels32(pixels);overlay.Apply(false,false);frame.annotations=annotations.ToArray();
            Atomic(Path.Combine(output,"rgb",id+".png"),rgbBytes);
            Atomic(Path.Combine(output,"overlays",id+".png"),overlay.EncodeToPNG());
            ExportSensors(spectral,frame);
            Atomic(Path.Combine(output,"labels",id+".txt"),labels.ToString());Atomic(Path.Combine(output,"annotations",id+".json"),JsonUtility.ToJson(frame,true));
            Atomic(Path.Combine(output,"labels-recognizable",id+".txt"),recognizableLabels.ToString());
            coco.images.Add(new DatasetCocoImage{id=imageId,width=config.width,height=config.height,file_name="rgb/"+id+".png"});
            foreach(var item in cocoObjects) {item.id=coco.annotations.Count+1;coco.annotations.Add(item);}
            if(observerExclusion!=null) {
                // Commit the pair only after this frame's RGB, annotations and
                // normal capture products are successfully written.
                observerExclusionManifest.frames.Add(observerExclusion);
                Atomic(Path.Combine(output,"observer-exclusion.json"),JsonUtility.ToJson(observerExclusionManifest,true));
            }
        }
        ObserverExclusionFrame ExportObserverExclusion(DatasetMultiInstanceMaskPass pass,DatasetSequenceFrame frame,string rgbHash)
        {
            if(pass.observerRenderers==null||pass.observerRenderers.Length==0) return null;
            if(pass.Error!=null||pass.ObserverVisible==null||pass.Frame!=frame.unityFrame||
                frame.width!=config.width||frame.height!=config.height)
                throw new InvalidOperationException("Observer exclusion is missing, stale or differs from the RGB frame.");
            string directory=Path.Combine(output,"observer-exclusion");Directory.CreateDirectory(directory);
            Read(pass.ObserverVisible.rt,visible);
            string relative="observer-exclusion/"+frame.imageId+".png";
            var maskBytes=EncodeMask(visible.GetPixels32());Atomic(Path.Combine(output,relative),maskBytes);
            frame.observerExclusionFile=relative;frame.observerExclusionUnityFrame=pass.Frame;
            return new ObserverExclusionFrame{imageFile="rgb/"+frame.imageId+".png",maskFile=relative,
                rgbSha256=rgbHash,maskSha256=Hash(maskBytes),unityFrame=frame.unityFrame};
        }
        static string Hash(byte[] bytes)
        {
            using(var algorithm=SHA256.Create()) return BitConverter.ToString(algorithm.ComputeHash(bytes)).Replace("-","").ToLowerInvariant();
        }
        static void Read(RenderTexture rt,Texture2D destination)
        {
            var old=RenderTexture.active;try {RenderTexture.active=rt;destination.ReadPixels(new Rect(0,0,destination.width,destination.height),0,0,false);destination.Apply(false,false);}
            finally {RenderTexture.active=old;}
        }
        byte[] EncodeMask(Color32[] values)
        {
            // R8 GPU targets expand to red-only when read as RGB. Save an
            // actual monochrome PNG so consumers converting to luminance do
            // not silently turn white foreground into 76/255 red luminance.
            var data=maskPng.GetRawTextureData<byte>();
            for(int i=0;i<values.Length;i++) data[i]=values[i].r>=128?(byte)255:(byte)0;
            maskPng.Apply(false,false);return maskPng.EncodeToPNG();
        }
        public void FinalizeIndex()
        {
            Atomic(Path.Combine(output,"annotations.coco.json"),JsonUtility.ToJson(coco,true));Atomic(Path.Combine(output,"review-required.txt"),string.Join("\n",review));
            var usable=new Coco{sequence_id=coco.sequence_id,categories=coco.categories,images=coco.images,annotations=coco.annotations.Where(a=>a.recognition_status=="R").ToList()};
            Atomic(Path.Combine(output,"annotations.recognizable.coco.json"),JsonUtility.ToJson(usable,true));
            FinalizeSensorCoco();
            Atomic(Path.Combine(output,"index.html"),DatasetSequenceGallery.Build(coco.images.Select(i=>Path.GetFileNameWithoutExtension(i.file_name)).ToArray(),config.width,config.height,Boxes,config.sensors));
        }
        public void Dispose() {UnityEngine.Object.Destroy(visible);UnityEngine.Object.Destroy(amodal);UnityEngine.Object.Destroy(overlay);UnityEngine.Object.Destroy(maskPng);if(sensorPixels!=null) UnityEngine.Object.Destroy(sensorPixels);}
        public static void Atomic(string path,string value) => Atomic(path,Encoding.UTF8.GetBytes(value));
        public static void Atomic(string path,byte[] value) {string tmp=path+".partial";File.WriteAllBytes(tmp,value);if(File.Exists(path)) File.Replace(tmp,path,null);else File.Move(tmp,path);}
    }
}
