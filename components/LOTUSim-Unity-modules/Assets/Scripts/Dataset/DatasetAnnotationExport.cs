using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;

namespace Lotusim.Dataset
{
    [Serializable] public sealed class DatasetMaskStats
    {
        public int area;
        public int[] bbox=Array.Empty<int>(); // x,y,width,height, top-left, inclusive pixel extent
        public bool touchesImageEdge;
    }
    [Serializable] public sealed class DatasetFrameAnnotation
    {
        public string schema="lotusim-instance-geometry-1",instance,category,displayName;
        public string policy="nearest_depth_water_is_opaque",visibilityMeaning="geometric_not_recognizability";
        public string maskFile,amodalMaskFile,overlayFile;
        public int categoryId,yoloClassIndex=0,unityFrame,visiblePixels,amodalPixelsInFrame;
        public int trackId=1;
        public float geometricVisibleFractionInFrame;
        public float visiblePercent,occludedPercent,rgbLocalContrast;
        public int contrastBackgroundPixels;
        public int[] amodalBBoxInFrame=Array.Empty<int>();
        public string recognitionStatus="NR",recognitionReason="",recognitionRuleVersion="",recognitionMeaning="",recognitionModality="rgb";
        public bool annotationPresent,needsManualReview,truncatedInFrame;
        public string reviewReason="";
        public int[] bbox=Array.Empty<int>();
        public int[] overlayLabelBox=Array.Empty<int>();
    }
    [Serializable] public sealed class DatasetCocoRle {public int[] size,counts;}
    [Serializable] public sealed class DatasetCocoImage {public int id,width,height;public string file_name;}
    [Serializable] public sealed class DatasetCocoCategory {public int id;public string name,displayName,supercategory="maritime_object";}
    [Serializable] public sealed class DatasetCocoAnnotation
    {
        public int id,image_id,category_id,area,iscrowd=0;
        public int[] bbox;
        public DatasetCocoRle segmentation;
    }
    [Serializable] public sealed class DatasetCoco
    {
        public string annotation_policy="nearest_depth_water_is_opaque";
        public List<DatasetCocoImage> images=new List<DatasetCocoImage>();
        public List<DatasetCocoAnnotation> annotations=new List<DatasetCocoAnnotation>();
        public DatasetCocoCategory[] categories;
    }
    [Serializable] public sealed class DatasetClassMap
    {
        public int yolo_index=0,coco_category_id;
        public string name,displayName;
    }

    public sealed class DatasetAnnotationExport : IDisposable
    {
        readonly string m_output,m_instance,m_category,m_displayName;
        readonly int m_classId,m_width,m_height;
        readonly DatasetAnnotationSettings m_settings;
        readonly DatasetCoco m_coco=new DatasetCoco();
        readonly List<string> m_review=new List<string>();
        readonly Texture2D m_visible,m_amodal,m_overlay;
        public int Count=>m_coco.images.Count;
        public int Boxes=>m_coco.annotations.Count;

        public DatasetAnnotationExport(string output,int width,int height,string instance,string category,int classId,DatasetAnnotationSettings settings)
        {
            m_output=output;m_width=width;m_height=height;m_instance=instance;m_category=category;m_classId=classId;m_settings=settings;
            m_displayName=DatasetOverlayLabel.DisplayName(category,settings.displayName);
            foreach(string dir in new[]{"masks","amodal","overlays","labels","annotations"}) Directory.CreateDirectory(Path.Combine(output,dir));
            m_coco.categories=new[]{new DatasetCocoCategory{id=classId,name=category,displayName=m_displayName}};
            m_visible=new Texture2D(width,height,TextureFormat.RGB24,false,true);
            m_amodal=new Texture2D(width,height,TextureFormat.RGB24,false,true);
            m_overlay=new Texture2D(width,height,TextureFormat.RGB24,false,false);
            Atomic(Path.Combine(output,"classes.txt"),category+"\n");
            Atomic(Path.Combine(output,"class-map.json"),JsonUtility.ToJson(new DatasetClassMap{coco_category_id=classId,name=category,displayName=m_displayName},true));
        }

        public DatasetFrameAnnotation Export(string id,Texture2D rgb,RenderTexture visible,RenderTexture amodal,int unityFrame)
        {
            Read(visible,m_visible);Read(amodal,m_amodal);
            var mask=m_visible.GetPixels32();var full=m_amodal.GetPixels32();
            var stats=Measure(mask,m_width,m_height);var fullStats=Measure(full,m_width,m_height);
            for(int i=0;i<mask.Length;i++) if(mask[i].r>=128&&full[i].r<128)
                throw new InvalidOperationException("Visible mask is not a subset of the amodal mask; capture alignment is invalid.");
            var result=new DatasetFrameAnnotation{instance=m_instance,category=m_category,displayName=m_displayName,categoryId=m_classId,unityFrame=unityFrame,
                maskFile="masks/"+id+".png",amodalMaskFile="amodal/"+id+".png",overlayFile="overlays/"+id+".png",
                visiblePixels=stats.area,amodalPixelsInFrame=fullStats.area,bbox=stats.bbox,annotationPresent=stats.area>0,
                truncatedInFrame=fullStats.touchesImageEdge,geometricVisibleFractionInFrame=fullStats.area==0?0:(float)stats.area/fullStats.area};
            result.needsManualReview=stats.area<m_settings.reviewMinVisiblePixels||stats.area>0&&
                (stats.bbox[2]<m_settings.reviewMinBoxSidePixels||stats.bbox[3]<m_settings.reviewMinBoxSidePixels);
            result.reviewReason=stats.area==0?"no_visible_label_pixels":result.needsManualReview?"small_geometric_target":"";
            var clean=rgb.GetPixels32();DatasetRecognition.Assess(result,fullStats,clean,mask,m_width,m_height,m_settings.recognition);
            Atomic(Path.Combine(m_output,result.maskFile),m_visible.EncodeToPNG());
            Atomic(Path.Combine(m_output,result.amodalMaskFile),m_amodal.EncodeToPNG());
            string yolo=stats.area==0?"":Yolo(stats.bbox,m_width,m_height);
            Atomic(Path.Combine(m_output,"labels",id+".txt"),yolo);
            var pixels=clean;PaintOverlay(pixels,mask,stats,m_width,m_height,DatasetRecognition.Color(result.recognitionStatus));
            result.overlayLabelBox=DatasetOverlayLabel.Paint(pixels,m_width,m_height,stats,DatasetRecognition.Label(result),null,DatasetRecognition.Color(result.recognitionStatus));
            m_overlay.SetPixels32(pixels);m_overlay.Apply(false,false);
            Atomic(Path.Combine(m_output,result.overlayFile),m_overlay.EncodeToPNG());
            Atomic(Path.Combine(m_output,"annotations",id+".json"),JsonUtility.ToJson(result,true));
            int imageId=m_coco.images.Count+1;
            m_coco.images.Add(new DatasetCocoImage{id=imageId,width=m_width,height=m_height,file_name="rgb/"+id+".png"});
            if(stats.area>0) m_coco.annotations.Add(new DatasetCocoAnnotation{id=m_coco.annotations.Count+1,image_id=imageId,category_id=m_classId,
                area=stats.area,bbox=stats.bbox,segmentation=new DatasetCocoRle{size=new[]{m_height,m_width},counts=Rle(mask,m_width,m_height)}});
            if(result.needsManualReview) m_review.Add(id);
            return result;
        }

        static void Read(RenderTexture source,Texture2D destination)
        {
            var previous=RenderTexture.active;
            try {RenderTexture.active=source;destination.ReadPixels(new Rect(0,0,destination.width,destination.height),0,0,false);destination.Apply(false,false);}
            finally {RenderTexture.active=previous;}
        }
        public static DatasetMaskStats Measure(Color32[] mask,int width,int height)
        {
            if(mask==null||mask.Length!=checked(width*height)||width<=0||height<=0) throw new ArgumentException("Invalid mask dimensions.");
            int left=width,right=-1,bottom=height,top=-1,area=0;
            for(int y=0;y<height;y++) for(int x=0;x<width;x++) if(mask[y*width+x].r>=128) {
                area++;left=Math.Min(left,x);right=Math.Max(right,x);bottom=Math.Min(bottom,y);top=Math.Max(top,y);
            }
            return new DatasetMaskStats{area=area,bbox=area==0?Array.Empty<int>():new[]{left,height-1-top,right-left+1,top-bottom+1},
                touchesImageEdge=area>0&&(left==0||right==width-1||bottom==0||top==height-1)};
        }
        public static int[] Rle(Color32[] mask,int width,int height)
        {
            var counts=new List<int>();bool foreground=false;int run=0;
            // COCO runs are column-major with top-left origin. Unity readback is bottom-left.
            for(int x=0;x<width;x++) for(int y=0;y<height;y++) {
                bool value=mask[(height-1-y)*width+x].r>=128;
                if(value==foreground) run++;
                else {counts.Add(run);run=1;foreground=value;}
            }
            counts.Add(run);return counts.ToArray();
        }
        public static string Yolo(int[] bbox,int width,int height) => Yolo(bbox,width,height,0);
        public static string Yolo(int[] bbox,int width,int height,int classIndex) => string.Format(CultureInfo.InvariantCulture,"{4} {0:F8} {1:F8} {2:F8} {3:F8}\n",
            (bbox[0]+bbox[2]/2f)/width,(bbox[1]+bbox[3]/2f)/height,(float)bbox[2]/width,(float)bbox[3]/height,classIndex);
        public static void PaintOverlay(Color32[] rgb,Color32[] mask,DatasetMaskStats stats,int width,int height)
            =>PaintOverlay(rgb,mask,stats,width,height,new Color32(0,255,120,255));
        public static void PaintOverlay(Color32[] rgb,Color32[] mask,DatasetMaskStats stats,int width,int height,Color32 box)
        {
            var outline=box;
            for(int y=1;y<height-1;y++) for(int x=1;x<width-1;x++) {
                int i=y*width+x;if(mask[i].r>=128&&(mask[i-1].r<128||mask[i+1].r<128||mask[i-width].r<128||mask[i+width].r<128)) rgb[i]=outline;
            }
            if(stats.area==0) return;
            int l=stats.bbox[0],r=l+stats.bbox[2]-1,t=height-1-stats.bbox[1],b=t-stats.bbox[3]+1;
            for(int x=l;x<=r;x++) {rgb[b*width+x]=box;rgb[t*width+x]=box;}
            for(int y=b;y<=t;y++) {rgb[y*width+l]=box;rgb[y*width+r]=box;}
        }
        public void FinalizeIndex()
        {
            Atomic(Path.Combine(m_output,"annotations.coco.json"),JsonUtility.ToJson(m_coco,true));
            Atomic(Path.Combine(m_output,"review-required.txt"),string.Join("\n",m_review)+(m_review.Count==0?"":"\n"));
        }
        public void Dispose()
        {
            UnityEngine.Object.Destroy(m_visible);UnityEngine.Object.Destroy(m_amodal);UnityEngine.Object.Destroy(m_overlay);
        }
        static void Atomic(string path,string text) => Atomic(path,System.Text.Encoding.UTF8.GetBytes(text));
        static void Atomic(string path,byte[] bytes)
        {
            string temporary=path+".partial";File.WriteAllBytes(temporary,bytes);
            if(File.Exists(path)) File.Replace(temporary,path,null);else File.Move(temporary,path);
        }
    }
}
