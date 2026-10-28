using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Lotusim.Dataset;
using UnityEditor;
using UnityEditor.AddressableAssets;
using UnityEditor.AddressableAssets.Settings;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using UnityEngine.SceneManagement;
using Object=UnityEngine.Object;

namespace Lotusim.EditorTools
{
    // Imports only the audited local conversion, never network code at runtime.
    public static class MarineOpenBoatsBuilder
    {
        public const string Root="Assets/models/open_boats",Scene="Assets/Scenes/Models/OpenBoatsLibrary.unity";
        [Serializable] public sealed class MaterialInfo
        {
            public string name,baseMap,normalMap,maskMap,emissionMap,sourceAlpha;
            public float[] color,emission;public float metallic,smoothness,normalScale=1,coat;
            public bool doubleSided;
        }
        [Serializable] public sealed class ModelInfo
        {
            public string key,category,title,author,source,license,licenseUrl,sha256;
            public float lengthM,beamM,draftM,heightM;public int vertices,triangles,maxTextureSize;
            public MaterialInfo[] materials;public string[] changes;
        }
        [MenuItem("LOTUSim/Models/External CC-BY boats/1 - Build or refresh audited prefabs")]
        public static void BuildAll()
        {
            if(EditorApplication.isPlayingOrWillChangePlaymode) throw new InvalidOperationException("Quit Play before importing boat prefabs.");
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            foreach(string key in DatasetBoatVariants.Models) Build(key);
            AssetDatabase.SaveAssets();Validate();CreateShowcase();
            Debug.Log("[Open Boats] Six external CC BY 4.0 prefabs ready. Original boats and dataset class IDs are unchanged.");
        }
        public static ModelInfo Info(string key)=>JsonUtility.FromJson<ModelInfo>(File.ReadAllText(Root+"/"+key+"/model-info.json"));
        static void Build(string key)
        {
            string folder=Root+"/"+key;var info=Info(key);
            if(info.key!=key||info.license!="CC-BY-4.0"||info.sha256.Length!=64) throw new InvalidDataException("Unaudited model: "+key);
            var materials=info.materials.Select((m,i)=>Material(folder,m,i)).ToArray();Folder(folder+"/Meshes");
            string path="Assets/Prefabs/"+key+".prefab";
            var old=AssetDatabase.LoadAssetAtPath<GameObject>(path);
            if(old!=null&&old.GetComponent<OpenBoatAssetCredit>()==null) throw new IOException("Refusing to overwrite unrelated prefab: "+path);
            var scene=EditorSceneManager.NewPreviewScene();var root=new GameObject(key);SceneManager.MoveGameObjectToScene(root,scene);
            try {
                var visual=new GameObject(MarineVesselWaveMotion.VisualChildName);visual.transform.SetParent(root.transform,false);
                using(var stream=new BinaryReader(File.OpenRead(folder+"/geometry.bytes"))) {
                    if(stream.ReadUInt32()!=0x4C424D31) throw new InvalidDataException("Invalid baked mesh header");
                    int parts=stream.ReadInt32();if(parts<1||parts>200) throw new InvalidDataException("Invalid material batch count");
                    for(int part=0;part<parts;part++) {
                        int material=stream.ReadInt32(),count=stream.ReadInt32(),indices=stream.ReadInt32();
                        if(material<0||material>=materials.Length||count<3||count>5000000||indices<3||indices%3!=0||indices>15000000) throw new InvalidDataException("Invalid baked mesh allocation");
                        var vertices=new Vector3[count];var normals=new Vector3[count];var uv=new Vector2[count];
                        for(int i=0;i<count;i++) {vertices[i]=new Vector3(stream.ReadSingle(),stream.ReadSingle(),stream.ReadSingle());normals[i]=new Vector3(stream.ReadSingle(),stream.ReadSingle(),stream.ReadSingle());uv[i]=new Vector2(stream.ReadSingle(),stream.ReadSingle());}
                        var triangles=new int[indices];for(int i=0;i<indices;i++) {triangles[i]=stream.ReadInt32();if(triangles[i]<0||triangles[i]>=count) throw new InvalidDataException("Invalid triangle index");}
                        var mesh=new Mesh{name=key+"_"+material,indexFormat=IndexFormat.UInt32,vertices=vertices,normals=normals,uv=uv,triangles=triangles};mesh.RecalculateBounds();mesh.RecalculateTangents();
                        string meshPath=folder+"/Meshes/material_"+material+".asset";var existing=AssetDatabase.LoadAssetAtPath<Mesh>(meshPath);
                        if(existing!=null) {EditorUtility.CopySerialized(mesh,existing);Object.DestroyImmediate(mesh);mesh=existing;EditorUtility.SetDirty(mesh);} else AssetDatabase.CreateAsset(mesh,meshPath);
                        var batch=new GameObject(info.materials[material].name);batch.transform.SetParent(visual.transform,false);batch.AddComponent<MeshFilter>().sharedMesh=mesh;batch.AddComponent<MeshRenderer>().sharedMaterial=materials[material];
                    }
                    if(stream.BaseStream.Position!=stream.BaseStream.Length) throw new InvalidDataException("Trailing baked mesh data");
                }
                for(int i=0;i<3;i++) {var col=new GameObject("Hull collision "+i);col.transform.SetParent(visual.transform,false);col.transform.localPosition=new Vector3((i-1)*info.lengthM*.27f,-info.draftM*.4f,0);col.AddComponent<BoxCollider>().size=new Vector3(info.lengthM*.30f,info.draftM,info.beamM*(i==2?.5f:.74f));}
                var body=root.AddComponent<Rigidbody>();body.isKinematic=true;body.useGravity=false;
                var wave=root.AddComponent<MarineVesselWaveMotion>();wave.visual=visual.transform;wave.parameters=new MarineVesselParameters{lengthM=info.lengthM,beamM=info.beamM,draftM=info.draftM,blockCoefficient=.30f,maxRollDeg=24,maxPitchDeg=16};wave.parameters.Validate();body.mass=wave.parameters.MassKg;
                root.AddComponent<OpenBoatAssetCredit>().credit=new OpenBoatCredit{model=key,title=info.title,author=info.author,source=info.source,license=info.license,licenseUrl=info.licenseUrl,sha256=info.sha256,changes=info.changes};
                if(PrefabUtility.SaveAsPrefabAsset(root,path)==null) throw new IOException("Cannot save "+path);Register(path,key);
            } finally {Object.DestroyImmediate(root);EditorSceneManager.ClosePreviewScene(scene);}
        }
        public static Material Material(string folder,MaterialInfo info,int index)
        {
            string path=folder+"/material_"+index+".mat";var value=AssetDatabase.LoadAssetAtPath<Material>(path);
            if(value==null) {value=new Material(Shader.Find("HDRP/Lit")){name=info.name};AssetDatabase.CreateAsset(value,path);}
            // glTF factors are linear. The source glass is intentionally opaque
            // for our existing nearest-depth annotation policy (documented).
            value.SetColor("_BaseColor",new Color(info.color[0],info.color[1],info.color[2],1));
            value.SetFloat("_Metallic",info.metallic);value.SetFloat("_Smoothness",info.smoothness);value.SetFloat("_CoatMask",info.coat);
            value.SetFloat("_SurfaceType",0);value.SetFloat("_AlphaCutoffEnable",0);value.SetFloat("_DoubleSidedEnable",info.doubleSided?1:0);value.enableInstancing=true;
            SetMap(value,"_BaseColorMap",folder,info.baseMap,true,false);SetMap(value,"_NormalMap",folder,info.normalMap,false,true);
            SetMap(value,"_MaskMap",folder,info.maskMap,false,false);SetMap(value,"_EmissiveColorMap",folder,info.emissionMap,true,false);
            value.SetFloat("_NormalScale",info.normalScale);value.SetFloat("_MetallicRemapMin",0);value.SetFloat("_MetallicRemapMax",1);value.SetFloat("_SmoothnessRemapMin",0);value.SetFloat("_SmoothnessRemapMax",1);
            value.SetColor("_EmissiveColor",new Color(info.emission[0],info.emission[1],info.emission[2]));HDMaterial.ValidateMaterial(value);EditorUtility.SetDirty(value);return value;
        }
        static void SetMap(Material material,string property,string folder,string file,bool srgb,bool normal)
        {
            if(string.IsNullOrEmpty(file)) {material.SetTexture(property,null);return;}
            string path=folder+"/"+file;var importer=AssetImporter.GetAtPath(path) as TextureImporter;
            if(importer==null) throw new FileNotFoundException(path);
            importer.textureType=normal?TextureImporterType.NormalMap:TextureImporterType.Default;importer.sRGBTexture=srgb;importer.maxTextureSize=4096;
            importer.mipmapEnabled=true;importer.anisoLevel=8;importer.wrapMode=TextureWrapMode.Repeat;importer.textureCompression=TextureImporterCompression.CompressedHQ;importer.SaveAndReimport();
            material.SetTexture(property,AssetDatabase.LoadAssetAtPath<Texture2D>(path));
        }
        public static void Register(string path,string key)
        {
            var settings=AddressableAssetSettingsDefaultObject.Settings??AddressableAssetSettingsDefaultObject.GetSettings(true);
            var group=settings.FindGroup("SpawnInterface")??settings.DefaultGroup;string guid=AssetDatabase.AssetPathToGUID(path);
            if(settings.groups.Where(g=>g!=null).SelectMany(g=>g.entries).Any(e=>e.address==key&&e.guid!=guid)) throw new InvalidOperationException("Address already owned by another model: "+key);
            settings.CreateOrMoveEntry(guid,group).address=key;EditorUtility.SetDirty(group);EditorUtility.SetDirty(settings);
        }
        [MenuItem("LOTUSim/Models/External CC-BY boats/2 - Open wave inspection scene")]
        public static void Open()
        {
            if(EditorApplication.isPlayingOrWillChangePlaymode) throw new InvalidOperationException("Quit Play first.");
            if(!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            CreateShowcase();EditorSceneManager.OpenScene(Scene);
        }
        static void CreateShowcase()
        {
            if(File.Exists(Scene)) return;
            MarineLibraryBuilder.CreateShowcase();var scene=EditorSceneManager.OpenScene(MarineLibraryBuilder.ShowcaseScene,OpenSceneMode.Additive);
            try {
                var host=scene.GetRootGameObjects().SelectMany(r=>r.GetComponentsInChildren<MarineLibraryShowcase>()).Single();
                host.prefabs=DatasetBoatVariants.Models.Select(n=>AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/"+n+".prefab")).ToArray();host.displayNames=DatasetBoatVariants.DisplayNames;
                if(!EditorSceneManager.SaveScene(scene,Scene,true)) throw new IOException("Cannot save external boat scene");
            } finally {EditorSceneManager.CloseScene(scene,true);}
        }
        [MenuItem("LOTUSim/Models/External CC-BY boats/3 - Enable variants in connected dataset")]
        public static void EnableVariants()
        {
            if(EditorApplication.isPlayingOrWillChangePlaymode) throw new InvalidOperationException("Quit Play first.");
            var config=AssetDatabase.LoadAssetAtPath<DatasetSequenceConfig>(DatasetLotusimSceneBuilder.ConfigPath);
            if(config==null) throw new InvalidOperationException("Open Dataset menu 7 first.");
            Undo.RecordObject(config,"Enable external boat appearances");
            ConfigureVariants(config);
            EditorUtility.SetDirty(config);AssetDatabase.SaveAssets();DatasetLotusimSceneBuilder.ExportScenario();
            Debug.Log("[Open Boats] Variants enabled. Class IDs, encounter counts and trajectories retained; appearance sampled per seed/track. Dataset credits are exported automatically.");
        }
        public static void ConfigureVariants(DatasetSequenceConfig config)
        {
            foreach(var c in config.classes) {
                var added=DatasetBoatVariants.Models.Where((n,i)=>DatasetBoatVariants.Categories[i]==c.category).Select(n=>AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/"+n+".prefab")).ToArray();
                if(added.Length==0) continue;if(added.Any(p=>p==null)) throw new InvalidOperationException("Build/import all audited prefabs first.");
                c.prefabVariants=(c.prefabVariants??Array.Empty<GameObject>()).Concat(added).Distinct().ToArray();
            }
            config.Validate();
        }
        [MenuItem("LOTUSim/Models/External CC-BY boats/Validate audited library")]
        public static void Validate()
        {
            foreach(string key in DatasetBoatVariants.Models) {
                var p=AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/"+key+".prefab");var info=Info(key);
                if(p==null||p.GetComponent<OpenBoatAssetCredit>()?.credit.license!="CC-BY-4.0"||p.GetComponent<MarineVesselWaveMotion>()?.visual==null||!p.GetComponent<Rigidbody>().isKinematic) throw new InvalidDataException("Incomplete boat: "+key);
                var renderers=p.GetComponentsInChildren<MeshRenderer>();int triangles=0;var bounds=new Bounds();bool first=true;
                foreach(var r in renderers) {var mesh=r.GetComponent<MeshFilter>().sharedMesh;MarineLibraryBuilder.CheckMesh(mesh);triangles+=mesh.triangles.Length/3;if(first) {bounds=r.bounds;first=false;} else bounds.Encapsulate(r.bounds);
                    if(r.sharedMaterials.Any(m=>m==null||m.shader.name!="HDRP/Lit"||m.GetFloat("_SurfaceType")!=0||m.GetFloat("_AlphaCutoffEnable")!=0)) throw new InvalidDataException("Unsupported annotation material: "+key);}
                if(triangles!=info.triangles||Math.Abs(bounds.size.x-info.lengthM)>.02f||bounds.min.y>=0||bounds.max.y<=0||p.GetComponentsInChildren<Camera>().Length!=0||p.GetComponentsInChildren<SkinnedMeshRenderer>().Length!=0||p.GetComponentsInChildren<Collider>().Length!=3) throw new InvalidDataException("Geometry/units/waterline regression: "+key);
                Debug.Log("[Open Boats] PASS "+key+": "+triangles+" triangles / "+info.lengthM+" m / CC BY credits / opaque masks / nine-point waves.");
            }
        }
        public static void Folder(string path) {if(AssetDatabase.IsValidFolder(path)) return;string parent=Path.GetDirectoryName(path).Replace('\\','/');Folder(parent);AssetDatabase.CreateFolder(parent,Path.GetFileName(path));}
    }
}
