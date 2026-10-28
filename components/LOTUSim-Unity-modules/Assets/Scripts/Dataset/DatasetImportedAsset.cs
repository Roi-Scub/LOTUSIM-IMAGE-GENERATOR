using System;
using UnityEngine;

namespace Lotusim.Dataset
{
    [Serializable] public sealed class DatasetImportedAssetRevision
    {
        public string model,revisionSha256,requestSha256,prefabGuid,prefabSha256;
    }
    // Ownership/provenance only. A mesh import never starts a campaign, opens
    // a network connection, or transfers trajectory ownership away from ROS.
    [DisallowMultipleComponent]
    public sealed class DatasetImportedAsset : MonoBehaviour
    {
        public string importId,model,requestSha256,revisionSha256,category,domain;
        public int classId;
        public float lengthM,beamM,heightM,draftM,maxSpeedMps,maxAltitudeM;
        public bool visualWaveResponse;
        public float visualDraftProxyM;
    }

    public static class DatasetImportedAssetRegistry
    {
        [Serializable] public sealed class Entry
        {
            public string model,category,prefabPath,prefabGuid,requestSha256,revisionSha256,importId;
            public int classId;
        }
        [Serializable] public sealed class Manifest
        {
            public string schema="lotusim-unity-imported-registry-1";
            public Entry[] assets=Array.Empty<Entry>();
        }
        static string previous;
        static Manifest manifest;
        public static int ClassId(string category)
        {
            switch(category) {
                case "buoy":return 1;case "drone":return 2;case "helicopter":return 3;
                case "airplane":return 4;case "bird":return 5;case "fishing_trawler":return 6;
                case "container_ship":return 7;case "motor_yacht":return 8;case "speedboat":return 9;
                case "jetski":return 10;case "ferry":return 11;case "sailboat":return 12;
                case "other":return 13;default:return 0;
            }
        }
        public static bool Matches(string model,string category)
        {
            if(!ModelKey(model)||ClassId(category)==0)return false;
            var source=Resources.Load<TextAsset>("DatasetImportedAssets");if(source==null)return false;
            if(previous!=source.text) {
                previous=source.text;
                try {manifest=JsonUtility.FromJson<Manifest>(previous);}catch {manifest=null;}
            }
            if(manifest?.schema!="lotusim-unity-imported-registry-1"||manifest.assets==null)return false;
            Entry match=null;
            foreach(var entry in manifest.assets) {
                if(entry==null||entry.model!=model)continue;
                if(match!=null)return false;match=entry;
            }
            return match!=null&&match.category==category&&match.classId==ClassId(category)&&
                match.prefabPath=="Assets/Prefabs/"+model+".prefab"&&Hex(match.prefabGuid,32)&&Hex(match.requestSha256,64)&&
                Hex(match.revisionSha256,64)&&match.importId=="import-"+Guid.ParseExact(model.Substring(7),"N").ToString("D");
        }
        public static bool ModelKey(string value)=>value!=null&&value.Length==39&&value.StartsWith("import_",StringComparison.Ordinal)&&Hex(value.Substring(7),32);
        public static bool Hex(string value,int count)
        {
            if(value==null||value.Length!=count)return false;
            foreach(char c in value)if(!(c>='0'&&c<='9')&&!(c>='a'&&c<='f'))return false;
            return true;
        }
    }
}
