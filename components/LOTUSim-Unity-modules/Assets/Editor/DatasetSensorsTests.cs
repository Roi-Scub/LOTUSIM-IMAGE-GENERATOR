using System;
using Lotusim.Dataset;
using UnityEditor;
using UnityEngine;
namespace Lotusim.EditorTools
{
    public static class DatasetSensorsTests
    {
        [MenuItem("LOTUSim/Dataset/Validate synthetic sensor settings")]
        public static void Run() {Check();CheckRigidMount();Debug.Log("[Sensors] PASS synthetic greybody model, validation, class mapping, rigid mount and multi-mode gallery.");}
        public static void CheckRigidMount()
        {
            var ship=new GameObject("Mount test ship");var host=new GameObject("Mount test host");var eye=new GameObject("Mount test camera");
            try {
                var wave=ship.AddComponent<MarineVesselWaveMotion>();wave.visual=new GameObject(MarineVesselWaveMotion.VisualChildName).transform;wave.visual.SetParent(ship.transform,false);
                var camera=eye.AddComponent<Camera>();eye.transform.position=new Vector3(1,2,3);var old=eye.transform.position;
                var mount=host.AddComponent<DatasetVesselCameraMount>();var offset=new Vector3(30.3f,12.4f,-5.5f);var rotation=Quaternion.Euler(2,105,0);
                mount.Attach(wave,camera,offset,rotation);ship.transform.rotation=Quaternion.Euler(0,-90,0);
                wave.visual.localRotation=Quaternion.Euler(4,0,7);wave.visual.localPosition=Vector3.up*1.2f;
                if(camera.transform.parent!=wave.visual||Vector3.Distance(camera.transform.localPosition,offset)>.00001f||Quaternion.Angle(camera.transform.rotation,wave.visual.rotation*rotation)>.001f)
                    throw new Exception("Camera did not follow rigid vessel roll / pitch.");
                wave.visual.localRotation=Quaternion.Euler(-3,0,-7);
                if(Quaternion.Angle(camera.transform.rotation,wave.visual.rotation*rotation)>.001f) throw new Exception("Idle preview lost camera mounting.");
                mount.Detach();if(camera.transform.parent!=null||Vector3.Distance(camera.transform.position,old)>.00001f) throw new Exception("Camera mount cleanup failed.");
            } finally {UnityEngine.Object.DestroyImmediate(host);UnityEngine.Object.DestroyImmediate(eye);UnityEngine.Object.DestroyImmediate(ship);}
        }
        public static void Check()
        {
            var settings=new DatasetSensorSettings{thermal=true,nightVision=true};settings.Validate();
            if(settings.Profile("bird").temperatureC!=39||settings.Profile("jetski").temperatureC<=settings.Profile("sailboat").temperatureC) throw new Exception("Thermal class priors missing.");
            for(float c=-50;c<=150;c+=5) {
                float actual=DatasetSensorSettings.ApparentTemperature(c,1,18);
                if(Mathf.Abs(actual-c)>.001f) throw new Exception("Unit-emissivity temperature mismatch.");
                if(DatasetSensorSettings.ApparentTemperature(c+1,.92f,18)<=DatasetSensorSettings.ApparentTemperature(c,.92f,18)) throw new Exception("Non-monotonic thermal proxy.");
            }
            string gallery=DatasetSequenceGallery.Build(new[]{"f000000"},3840,2160,12,settings);
            if(!gallery.Contains("3840 × 2160")||!gallery.Contains("nightvision")||!gallery.Contains("thermal")||!gallery.Contains("pixels natifs")) throw new Exception("4K multimodal gallery incomplete.");
            settings.thermalMaxC=settings.thermalMinC;
            try {settings.Validate();throw new Exception("Empty temperature window accepted");} catch(ArgumentException) {}
            settings=new DatasetSensorSettings();settings.nightGain=float.NaN;
            try {settings.Validate();throw new Exception("NaN night gain accepted");} catch(ArgumentException) {}
        }
    }
}
