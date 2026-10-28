using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;

namespace Lotusim.Dataset
{
    public sealed partial class DatasetSequenceExport
    {
        Texture2D sensorPixels;
        void InitializeSensors()
        {
            if(config.sensors==null||!config.sensors.Enabled) return;
            sensorPixels=new Texture2D(config.width,config.height,TextureFormat.RGB24,false,true);
            foreach(string mode in SensorModes()) {Directory.CreateDirectory(Path.Combine(output,mode));Directory.CreateDirectory(Path.Combine(output,"overlays-"+mode));}
        }
        IEnumerable<string> SensorModes()
        {
            if(config.sensors?.thermal==true) yield return "thermal";
            if(config.sensors?.nightVision==true) yield return "nightvision";
        }
        void ExportSensors(DatasetSpectralPass pass,DatasetSequenceFrame frame)
        {
            var descriptors=new List<DatasetSensorFrame>{new DatasetSensorFrame{mode="rgb",imageFile="rgb/"+frame.imageId+".png",overlayFile="overlays/"+frame.imageId+".png",
                model="Unity HDRP visible-light rendering",width=frame.width,height=frame.height,unityFrame=frame.unityFrame}};
            foreach(string mode in SensorModes()) {
                if(pass==null||pass.Frame!=frame.unityFrame) throw new InvalidOperationException("Sensor output is missing or stale; frame not committed.");
                var target=mode=="thermal"?pass.Thermal:pass.NightVision;
                if(target==null) throw new InvalidOperationException("Sensor render target missing: "+mode);
                Read(target.rt,sensorPixels);string raw=mode+"/"+frame.imageId+".png",annotated="overlays-"+mode+"/"+frame.imageId+".png";
                Atomic(Path.Combine(output,raw),DatasetRgbPng.Encode(sensorPixels));
                var pixels=sensorPixels.GetPixels32();var plates=new List<int[]>();
                foreach(var annotation in frame.annotations) {
                    var color=DatasetRecognition.Color(annotation.recognitionStatus);Box(pixels,annotation.bbox,frame.width,frame.height,color);
                    plates.Add(DatasetOverlayLabel.Paint(pixels,frame.width,frame.height,new DatasetMaskStats{area=annotation.visiblePixels,bbox=annotation.bbox},DatasetRecognition.Label(annotation),plates,color));
                }
                overlay.SetPixels32(pixels);overlay.Apply(false,false);Atomic(Path.Combine(output,annotated),DatasetRgbPng.Encode(overlay));
                descriptors.Add(new DatasetSensorFrame{mode=mode,imageFile=raw,overlayFile=annotated,width=frame.width,height=frame.height,unityFrame=frame.unityFrame,
                    model=mode=="thermal"?"synthetic surface-temperature greybody T4 proxy; not calibrated LWIR":"synthetic HDR intensification / green tint / noise / vignette; not calibrated NVG"});
            }
            frame.sensors=descriptors.ToArray();
        }
        static void Box(Color32[] pixels,int[] b,int w,int h,Color32 color)
        {
            var green=color;int stroke=Mathf.Max(1,w/1920);
            for(int t=0;t<stroke;t++) {
                for(int x=b[0];x<b[0]+b[2];x++) {pixels[(h-1-Mathf.Min(h-1,b[1]+t))*w+x]=green;pixels[(h-1-Mathf.Max(0,b[1]+b[3]-1-t))*w+x]=green;}
                for(int y=b[1];y<b[1]+b[3];y++) {pixels[(h-1-y)*w+Mathf.Min(w-1,b[0]+t)]=green;pixels[(h-1-y)*w+Mathf.Max(0,b[0]+b[2]-1-t)]=green;}
            }
        }
        void FinalizeSensorCoco()
        {
            foreach(string mode in SensorModes()) {
                var copy=new Coco{annotation_policy=coco.annotation_policy,sequence_id=coco.sequence_id,categories=coco.categories,annotations=coco.annotations,
                    images=coco.images.Select(i=>new DatasetCocoImage{id=i.id,width=i.width,height=i.height,file_name=mode+"/"+Path.GetFileName(i.file_name)}).ToList()};
                Atomic(Path.Combine(output,"annotations."+mode+".coco.json"),JsonUtility.ToJson(copy,true));
            }
        }
    }
}
