using System;
using System.Collections;
using System.IO;
using System.Linq;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace Lotusim.Dataset
{
    [Serializable] public sealed class DatasetManualEnvironment
    {
        public string timeOfDay="day";
        public float cloudCover,rainIntensity,waveHeightM=1.2f,waveDirectionDeg=35,windMps=6;
        public void Validate()
        {
            if(!new[]{"day","dusk","night"}.Contains(timeOfDay)||!Range(cloudCover,0,1)||!Range(rainIntensity,0,1)||
                !Range(waveHeightM,0,8)||!Range(waveDirectionDeg,0,360)||!Range(windMps,0,30))throw new ArgumentException("Invalid manual weather settings.");
        }
        public DatasetSeaPreset Sea()
        {
            Validate();float level=waveHeightM/8;
            // This deliberately is not a conversion of significant wave height
            // into a measured HDRP height. Archive the request and actual proxy.
            return new DatasetSeaPreset{name="manual_uncalibrated_wave_height_proxy",windKmh=waveHeightM==0?0:Mathf.Lerp(18,110,Mathf.Sqrt(level)),
                band0=waveHeightM==0?0:Mathf.Lerp(.12f,1,level),band1=waveHeightM==0?0:Mathf.Lerp(.1f,1,level),
                ripplesKmh=Mathf.Min(30,windMps*3.6f),foam=Mathf.Lerp(.02f,.7f,level),patchSizeM=512,directionDeg=waveDirectionDeg,cameraMotionScale=level};
        }
        public static bool Range(float v,float a,float b)=>!float.IsNaN(v)&&!float.IsInfinity(v)&&v>=a&&v<=b;
    }
    [Serializable] public sealed class DatasetManualObjectRequest
    {
        public string id,model,distanceMode="metres";
        public int count=1;
        public float distanceM,bearingDeg,spreadDeg,altitudeM,speedMps,headingDeg,targetHeightPx;
    }
    [Serializable] public sealed class DatasetManualBlock
    {
        public string id,name;
        public int images;
        public DatasetManualEnvironment environment;
        public DatasetManualObjectRequest[] objects;
    }
    [Serializable] public sealed class DatasetManualCamera
    {
        public int width,height;
        public float verticalFovDeg,farClipM,viewHeadingDeg,viewDownPitchDeg;
        public string station;
    }
    [Serializable] public sealed class DatasetManualObserver
    {
        public float speedMps,headingDeg,rollMaxDeg,pitchMaxDeg;
    }
    [Serializable] public sealed class DatasetManualSensors {public bool rgb=true,thermal,nightVision;}
    [Serializable] public sealed class DatasetManualCampaignRequest
    {
        public string schema,name,engine,scene;
        public int seed,totalImages;
        public DatasetManualCamera camera;
        public DatasetManualObserver observer;
        public DatasetManualSensors sensors;
        public DatasetManualBlock[] blocks;
    }
    [Serializable] public sealed class DatasetManualObjectPlacement
    {
        public string requestId,instance,model,distanceMode;
        public float requestedHorizontalDistanceM,nominalBearingDeg,requestedTargetHeightPx,headingDeg;
    }
    [Serializable] public sealed class DatasetManualImageMetadata
    {
        public string schema="lotusim-manual-image-1",campaignId,campaignSha256,blockId,blockName;
        public int imageInBlock,imageInCampaign;
        public bool independentImage=true,continuousVideo=false,waveHeightCalibrated=false,rainPhysicallyCalibrated=false;
        public string distanceDefinition="nominal_horizontal_camera_range_before_visual_wave_response";
        public string weatherModel="HDRP cloud layer and bounded visual rain; requested wave metres mapped to uncalibrated spectrum proxy";
        public string collisionPolicy="nominal image placement only; not a certified traffic or hydrodynamic safety plan";
        public DatasetManualEnvironment environment;
        public DatasetManualObjectPlacement[] placements;
    }
}
