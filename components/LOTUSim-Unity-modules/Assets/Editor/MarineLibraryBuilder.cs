using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Lotusim.Dataset;
using UnityEditor;
using UnityEditor.AddressableAssets;
using UnityEditor.AddressableAssets.Settings;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering.HighDefinition;
using Object=UnityEngine.Object;

namespace Lotusim.EditorTools
{
    // Original generic vessels, not replicas of a manufacturer or licensed CAD.
    public static partial class MarineLibraryBuilder
    {
        public const string LibraryPath="Assets/models/marine_library";
        const string Marker=MarineVesselWaveMotion.VisualChildName;
        const int White=0,Blue=1,Antifoul=2,Black=3,Teak=4,Glass=5,Steel=6,DarkMetal=7,Orange=8,Canvas=9,RopeMat=10,Net=11,
            CargoRed=12,CargoBlue=13,CargoGreen=14,CargoGrey=15,CargoBrown=16,Deck=17,NavRed=18,NavGreen=19,NavWhite=20,Rubber=21,Cream=22,GreyHull=23,Yellow=24;
        static readonly string[] MaterialNames={"GelcoatWhite","MarineBlue","AntifoulingRed","BlackPolymer","TeakDeck","OpaqueTintedGlazing","StainlessSteel","WeatheredSteel","RescueOrange","Sailcloth","Rope","FishingNet",
            "ContainerRed","ContainerBlue","ContainerGreen","ContainerGrey","ContainerBrown","NonSlipDeck","NavigationRed","NavigationGreen","NavigationWhite","FenderRubber","Upholstery","HullGrey","SafetyYellow"};
        static readonly Color[] Colors={new Color(.8f,.82f,.8f),new Color(.018f,.13f,.23f),new Color(.30f,.045f,.025f),new Color(.015f,.021f,.028f),new Color(.36f,.21f,.10f),new Color(.009f,.024f,.035f),new Color(.5f,.53f,.55f),new Color(.09f,.12f,.14f),new Color(.92f,.21f,.035f),new Color(.82f,.80f,.72f),new Color(.40f,.31f,.17f),new Color(.045f,.13f,.10f),
            new Color(.48f,.075f,.045f),new Color(.035f,.15f,.32f),new Color(.055f,.25f,.20f),new Color(.59f,.58f,.52f),new Color(.29f,.15f,.08f),new Color(.15f,.18f,.18f),new Color(.48f,.002f,.003f),new Color(.002f,.35f,.025f),new Color(.84f,.84f,.75f),new Color(.018f,.02f,.022f),new Color(.73f,.65f,.48f),new Color(.30f,.36f,.39f),new Color(.90f,.60f,.025f)};
        static Material[] palette;
        [Serializable] sealed class ModelInfo
        {
            public string model,displayName,prefab,source="original procedural marine geometry",forwardAxis="Unity +X / Gazebo +X";
            public int classId,triangles,vertices,geometryOperations,materialSlots;
            public Vector3 boundsMin,boundsMax;
            public MarineVesselParameters flotation;
            public bool defaultRootKinematic=true,freeRigidbodyAvailable=true,validatedHydrodynamics=false;
        }
        [MenuItem("LOTUSim/Models/Build detailed marine library (7 vessels)")]
        public static void BuildAll()
        {
            if(EditorApplication.isPlayingOrWillChangePlaymode) throw new InvalidOperationException("Quit Play before building marine models.");
            Folder("Assets/Prefabs");Folder(LibraryPath+"/Materials");Folder(LibraryPath+"/Textures");CreatePalette();
            for(int i=0;i<MarineVesselCatalog.Models.Length;i++) BuildOne(i);
            AssetDatabase.SaveAssets();
            Debug.Log("[Marine Library] READY: seven detailed opaque HDRP prefabs, wave response, opt-in Rigidbody buoyancy, Addressables and matching Gazebo geometry.");
        }
        static void BuildOne(int index)
        {
            string name=MarineVesselCatalog.Models[index],path="Assets/Prefabs/"+name+".prefab",folder=LibraryPath+"/"+name;
            Folder(folder+"/Meshes");var existing=AssetDatabase.LoadAssetAtPath<GameObject>(path);
            if(existing!=null&&existing.transform.Find(Marker)==null) throw new IOException("Refusing to replace a user prefab: "+path);
            var geometry=new Geometry();var p=MarineVesselCatalog.Parameters(index);
            if(index==0) Trawler(geometry,p);else if(index==1) ContainerShip(geometry,p);else if(index==2) Yacht(geometry,p);
            else if(index==3) Speedboat(geometry,p);else if(index==4) Jetski(geometry,p);else if(index==5) Ferry(geometry,p);else Sailboat(geometry,p);
            Mesh generated=geometry.ToMesh(name,out var slots);CheckMesh(generated);
            string meshPath=folder+"/Meshes/CompleteVessel.asset";var mesh=AssetDatabase.LoadAssetAtPath<Mesh>(meshPath);
            if(mesh==null) {mesh=generated;AssetDatabase.CreateAsset(mesh,meshPath);}else {EditorUtility.CopySerialized(generated,mesh);Object.DestroyImmediate(generated);EditorUtility.SetDirty(mesh);}
            var scene=EditorSceneManager.NewPreviewScene();var root=existing==null?new GameObject(name):PrefabUtility.LoadPrefabContents(path);
            if(existing==null) UnityEngine.SceneManagement.SceneManager.MoveGameObjectToScene(root,scene);
            try {
                var old=root.transform.Find(Marker);if(old!=null) Object.DestroyImmediate(old.gameObject);
                var visual=new GameObject(Marker);visual.transform.SetParent(root.transform,false);
                var appearance=new GameObject("Hull, superstructure and equipment");appearance.transform.SetParent(visual.transform,false);
                appearance.AddComponent<MeshFilter>().sharedMesh=mesh;appearance.AddComponent<MeshRenderer>().sharedMaterials=slots.Select(s=>palette[s]).ToArray();
                // Simple compound collision volumes remain separate from the
                // detailed mesh. No non-convex dynamic MeshCollider is used.
                for(int i=0;i<3;i++) {
                    var col=new GameObject("Hull collision "+i);col.transform.SetParent(visual.transform,false);
                    col.transform.localPosition=new Vector3((i-1)*p.lengthM*.27f,-p.draftM*.15f,0);
                    col.AddComponent<BoxCollider>().size=new Vector3(p.lengthM*.30f,p.draftM*1.2f,p.beamM*(i==2?.50f:.76f));
                }
                var body=root.GetComponent<Rigidbody>();if(body==null) body=root.AddComponent<Rigidbody>();body.isKinematic=true;body.useGravity=false;body.mass=p.MassKg;
                var response=root.GetComponent<MarineVesselWaveMotion>();if(response==null) {response=root.AddComponent<MarineVesselWaveMotion>();response.parameters=p;}
                response.visual=visual.transform;response.mode=MarineWaveMode.VisualResponse;
                var prefab=PrefabUtility.SaveAsPrefabAsset(root,path);if(prefab==null) throw new IOException("Cannot save "+path);
                Register(path,name);
                var info=new ModelInfo{model=name,displayName=MarineVesselCatalog.DisplayNames[index],prefab=path,classId=index+6,vertices=mesh.vertexCount,triangles=mesh.triangles.Length/3,
                    materialSlots=slots.Length,geometryOperations=geometry.parts,boundsMin=mesh.bounds.min,boundsMax=mesh.bounds.max,flotation=p};
                string json=JsonUtility.ToJson(info,true);File.WriteAllText(folder+"/model-info.json",json);
                Export(mesh,slots,name,index+6,json);
                Directory.CreateDirectory("artifacts/marine-library");File.WriteAllText("artifacts/marine-library/"+name+"-validation.json",json);
                Debug.Log("[Marine Library] "+name+": "+info.triangles+" triangles, "+slots.Length+" material batches, "+p.lengthM+" m hull, approximate mass "+p.MassKg+" kg.");
            }
            finally {if(existing!=null) PrefabUtility.UnloadPrefabContents(root);else Object.DestroyImmediate(root);EditorSceneManager.ClosePreviewScene(scene);}
        }
        public static void RegisterExisting()
        {
            foreach(string name in MarineVesselCatalog.Models) {
                string path="Assets/Prefabs/"+name+".prefab";if(AssetDatabase.LoadAssetAtPath<GameObject>(path)==null) throw new FileNotFoundException(path);
                Register(path,name);
            }
            AssetDatabase.SaveAssets();
        }
        static void Register(string path,string name)
        {
            var settings=AddressableAssetSettingsDefaultObject.Settings;
            if(settings==null) settings=AddressableAssetSettingsDefaultObject.GetSettings(true);
            if(settings==null) throw new InvalidOperationException("Addressables settings unavailable.");
            var group=settings.FindGroup("SpawnInterface")??settings.DefaultGroup;
            if(group==null) throw new InvalidOperationException("No Addressables default group.");
            string guid=AssetDatabase.AssetPathToGUID(path);
            if(settings.groups.Where(g=>g!=null).SelectMany(g=>g.entries).Any(e=>e.address==name&&e.guid!=guid)) throw new InvalidOperationException("Address already belongs to another asset: "+name);
            var entry=settings.CreateOrMoveEntry(guid,group);entry.address=name;
            settings.SetDirty(AddressableAssetSettings.ModificationEvent.EntryModified,entry,true,true);EditorUtility.SetDirty(group);
        }
        static void CreatePalette()
        {
            palette=new Material[MaterialNames.Length];var paint=Textures("Paint");var wood=Textures("Wood");var cloth=Textures("Cloth");
            for(int i=0;i<palette.Length;i++) {
                string path=LibraryPath+"/Materials/"+MaterialNames[i]+".mat";var material=AssetDatabase.LoadAssetAtPath<Material>(path);
                if(material==null) {
                    var shader=Shader.Find("HDRP/Lit");if(shader==null) throw new InvalidOperationException("HDRP/Lit is required.");
                    material=new Material(shader){name=MaterialNames[i]};material.SetColor("_BaseColor",Colors[i]);
                    material.SetFloat("_Metallic",i==Steel?.9f:i==DarkMetal?.65f:i==Glass?.15f:.03f);
                    material.SetFloat("_Smoothness",i==Glass?.93f:i==Steel?.66f:i==Rubber?.2f:.43f);
                    material.SetFloat("_SurfaceType",0);material.SetFloat("_AlphaCutoffEnable",0);material.enableInstancing=true;
                    if(i!=Glass&&i!=Steel&&i<NavRed) {
                        var maps=i==Teak?wood:i==Canvas||i==RopeMat||i==Net?cloth:paint;
                        material.SetTexture("_BaseColorMap",maps[0]);material.SetTexture("_NormalMap",maps[1]);material.SetTexture("_MaskMap",maps[2]);material.SetFloat("_NormalScale",i==Teak?.3f:.17f);
                    }
                    if(i==NavRed||i==NavGreen||i==NavWhite) material.SetColor("_EmissiveColor",Colors[i]*2);
                    HDMaterial.ValidateMaterial(material);AssetDatabase.CreateAsset(material,path);
                }
                palette[i]=material;
            }
        }
        static Texture2D[] Textures(string kind)
        {
            const int n=512;var result=new Texture2D[3];string[] suffix={"Base","Normal","Mask"};
            for(int map=0;map<3;map++) {
                string path=LibraryPath+"/Textures/"+kind+"_"+suffix[map]+".png";var loaded=AssetDatabase.LoadAssetAtPath<Texture2D>(path);
                if(loaded!=null) {result[map]=loaded;continue;}
                var pixels=new Color32[n*n];
                for(int y=0;y<n;y++) for(int x=0;x<n;x++) {
                    float grain=Mathf.PerlinNoise(x*.09f+13,y*.09f+47),fine=Mathf.PerlinNoise(x*.55f+1,y*.55f+5);
                    float value=kind=="Wood"?.67f+.25f*Mathf.PerlinNoise(x*.035f,y*.55f):kind=="Cloth"?.92f+.04f*Mathf.Sin(x*1.7f)*Mathf.Sin(y*1.7f):.91f+.08f*grain;
                    if(kind=="Wood"&&x%64<2) value*=.38f;
                    if(map==0) pixels[y*n+x]=new Color(value,value,value,1);
                    else if(map==1) pixels[y*n+x]=new Color(.5f+(grain-.5f)*.16f,.5f+(fine-.5f)*.16f,1,1);
                    else pixels[y*n+x]=new Color(1,.88f+.12f*grain,0,.75f+.2f*fine);
                }
                var image=new Texture2D(n,n,TextureFormat.RGBA32,false,map!=0);image.SetPixels32(pixels);image.Apply();File.WriteAllBytes(path,image.EncodeToPNG());Object.DestroyImmediate(image);
                AssetDatabase.ImportAsset(path,ImportAssetOptions.ForceSynchronousImport);var importer=(TextureImporter)AssetImporter.GetAtPath(path);
                importer.textureType=map==1?TextureImporterType.NormalMap:TextureImporterType.Default;importer.sRGBTexture=map==0;importer.wrapMode=TextureWrapMode.Repeat;
                importer.mipmapEnabled=true;importer.anisoLevel=4;importer.textureCompression=TextureImporterCompression.Uncompressed;importer.SaveAndReimport();result[map]=AssetDatabase.LoadAssetAtPath<Texture2D>(path);
            }
            return result;
        }
        public static void CheckMesh(Mesh mesh)
        {
            var v=mesh.vertices;var normals=mesh.normals;
            if(v.Length==0||normals.Length!=v.Length||mesh.uv.Length!=v.Length||mesh.tangents.Length!=v.Length||v.Any(p=>!Finite(p))||normals.Any(p=>!Finite(p)||p.sqrMagnitude<.9f)) throw new InvalidOperationException("Invalid marine vertex attributes: "+mesh.name);
            foreach(int i in mesh.triangles) if(i<0||i>=v.Length) throw new InvalidOperationException("Marine triangle index outside vertex buffer.");
        }
        static bool Finite(Vector3 p)=>!(float.IsNaN(p.x)||float.IsNaN(p.y)||float.IsNaN(p.z)||float.IsInfinity(p.x)||float.IsInfinity(p.y)||float.IsInfinity(p.z));
        static string F(float value)=>value.ToString("G9",CultureInfo.InvariantCulture);
        static void Export(Mesh mesh,int[] slots,string name,int label,string json)
        {
            string target=Environment.GetEnvironmentVariable("LOTUSIM_MARINE_EXPORT_ROOT");
            if(string.IsNullOrEmpty(target)) target=Path.GetFullPath(Path.Combine(Application.dataPath,"../../LOTUSim/assets/models"));
            if(!Directory.Exists(target)) throw new DirectoryNotFoundException("Expected LOTUSim model folder: "+target);
            string dir=Path.Combine(target,name),marker=Path.Combine(dir,"marine-model-info.json");
            if(Directory.Exists(dir)&&!File.Exists(marker)) throw new IOException("Refusing to replace an unrelated LOTUSim model: "+dir);
            Directory.CreateDirectory(Path.Combine(dir,"meshes"));Directory.CreateDirectory(Path.Combine(dir,"materials"));
            using(var writer=new StreamWriter(Path.Combine(dir,"meshes",name+".obj"),false,new UTF8Encoding(false))) {
                writer.WriteLine("# Original LOTUSim marine library; X forward, Z up; metres.\nmtllib ../materials/"+name+".mtl");
                foreach(var p in mesh.vertices) writer.WriteLine("v "+F(p.x)+" "+F(p.z)+" "+F(p.y));
                foreach(var uv in mesh.uv) writer.WriteLine("vt "+F(uv.x)+" "+F(uv.y));
                foreach(var p in mesh.normals) writer.WriteLine("vn "+F(p.x)+" "+F(p.z)+" "+F(p.y));
                for(int sub=0;sub<slots.Length;sub++) {
                    writer.WriteLine("usemtl "+MaterialNames[slots[sub]]);var tris=mesh.GetTriangles(sub);
                    for(int i=0;i<tris.Length;i+=3) {int a=tris[i]+1,b=tris[i+2]+1,c=tris[i+1]+1;writer.WriteLine($"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}");}
                }
            }
            using(var writer=new StreamWriter(Path.Combine(dir,"materials",name+".mtl"))) foreach(int slot in slots) {
                Color c=Colors[slot];writer.WriteLine("newmtl "+MaterialNames[slot]+"\nKd "+F(c.r)+" "+F(c.g)+" "+F(c.b)+"\nKs 0.15 0.15 0.15\nNs 48\nd 1\nillum 2\n");
            }
            File.WriteAllText(Path.Combine(dir,"model.config"),"<?xml version=\"1.0\"?><model><name>"+name+"</name><version>1.0</version><sdf version=\"1.10\">model.sdf</sdf><description>Original detailed marine visual model. Unity wave response; no Gazebo hydrodynamics.</description></model>\n");
            File.WriteAllText(Path.Combine(dir,"model.sdf"),"<?xml version=\"1.0\"?><sdf version=\"1.10\"><model name=\""+name+"\"><static>true</static><link name=\"hull\"><visual name=\"appearance\"><geometry><mesh><uri>model://"+name+"/meshes/"+name+".obj</uri></mesh></geometry></visual></link><plugin filename=\"gz-sim-label-system\" name=\"gz::sim::systems::Label\"><label>"+label+"</label></plugin></model></sdf>\n");
            File.WriteAllText(marker,json);
        }
        static void Folder(string path)
        {
            path=path.Replace('\\','/');if(AssetDatabase.IsValidFolder(path)) return;
            string parent=Path.GetDirectoryName(path).Replace('\\','/');Folder(parent);AssetDatabase.CreateFolder(parent,Path.GetFileName(path));
        }
    }
}
