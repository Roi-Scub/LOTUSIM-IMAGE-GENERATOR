// Original procedural asset for LOTUSim; no third-party meshes or textures.
// This builder is Editor-only. The saved prefab has no runtime generator or physics.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.AddressableAssets;
using UnityEditor.AddressableAssets.Settings;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using Object = UnityEngine.Object;

namespace Lotusim.EditorTools
{
    [InitializeOnLoad]
    public static class MarineBuoyBuilder
    {
        const string PrefabPath = "Assets/Prefabs/buoy.prefab";
        const string AssetRoot = "Assets/models/buoy";
        const string VisualName = "MarineBuoyVisual_v1";
        const int Segments = 96;
        const int TextureSize = 1024;
        static bool attempted;

        static MarineBuoyBuilder()
        {
            EditorApplication.update += EnsureInitialBuild;
        }

        static void EnsureInitialBuild()
        {
            if (attempted || EditorApplication.isCompiling || EditorApplication.isUpdating ||
                EditorApplication.isPlayingOrWillChangePlaymode) return;
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath);
            if (prefab != null && prefab.transform.Find(VisualName) != null)
            {
                EditorApplication.update -= EnsureInitialBuild;
                if (!File.Exists("artifacts/buoy/preview-large.png")) QueuePreview(prefab);
                return;
            }
            attempted = true;
            EditorApplication.update -= EnsureInitialBuild;
            try { Build(); }
            catch (Exception exception) { Debug.LogException(exception); }
        }

        [MenuItem("LOTUSim/Models/Build realistic buoy")]
        public static void Build()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
                throw new InvalidOperationException("Stop Play before building the buoy prefab.");
            if (Shader.Find("HDRP/Lit") == null)
                throw new InvalidOperationException("The buoy requires the project's HDRP/Lit shader.");
            EnsureFolder("Assets/Prefabs");
            EnsureFolder(AssetRoot + "/Meshes");
            EnsureFolder(AssetRoot + "/Materials");
            EnsureFolder(AssetRoot + "/Textures");

            var maps = CreateWeatheredMaps();
            var paint = Material("WeatheredOrange", new Color(1, 1, 1), .05f, .36f);
            paint.SetTexture("_BaseColorMap", maps[0]);
            paint.SetTexture("_MaskMap", maps[1]);
            paint.SetTexture("_NormalMap", maps[2]);
            paint.SetFloat("_NormalScale", .28f);
            HDMaterial.ValidateMaterial(paint);
            EditorUtility.SetDirty(paint);

            var tape = Material("ReflectiveIvory", new Color(.83f, .82f, .70f), .25f, .72f);
            var rubber = Material("MarineRubber", new Color(.025f, .033f, .029f), 0, .30f);
            var steel = Material("GalvanizedSteel", new Color(.33f, .37f, .39f), .90f, .53f);
            var rustySteel = Material("OxidizedSteel", new Color(.19f, .12f, .075f), .58f, .28f);
            var darkMetal = Material("LanternHousing", new Color(.055f, .064f, .068f), .75f, .52f);
            var solar = Material("PhotovoltaicCells", Color.white, .52f, .72f);
            solar.SetTexture("_BaseColorMap", CreateSolarTexture());
            HDMaterial.ValidateMaterial(solar);
            EditorUtility.SetDirty(solar);
            var lens = Material("AmberFresnelLens", new Color(.48f, .13f, .012f), .08f, .94f);
            lens.SetColor("_EmissiveColor", new Color(1f, .30f, .018f) * 1.3f);
            lens.SetFloat("_AlbedoAffectEmissive", 0);
            HDMaterial.ValidateMaterial(lens);
            EditorUtility.SetDirty(lens);

            bool existing = File.Exists(PrefabPath);
            var root = existing ? PrefabUtility.LoadPrefabContents(PrefabPath) : new GameObject("buoy");
            try
            {
                // Only our own generated child is replaced; preserve user components and the prefab GUID.
                var previous = root.transform.Find(VisualName);
                if (previous != null) Object.DestroyImmediate(previous.gameObject);
                var visual = new GameObject(VisualName);
                visual.transform.SetParent(root.transform, false);
                BuildGeometry(visual.transform, paint, tape, rubber, steel, rustySteel, darkMetal, solar, lens);
                CombineByMaterial(visual.transform);
                var saved = PrefabUtility.SaveAsPrefabAsset(root, PrefabPath);
                if (saved == null) throw new InvalidOperationException("Unity could not save the buoy prefab.");
                RegisterAddress();
                AssetDatabase.SaveAssets();
                Validate(saved);
                QueuePreview(saved);
                Debug.Log("[MarineBuoyBuilder] READY: Assets/Prefabs/buoy.prefab; Addressables key=buoy; " +
                          "HDRP materials; sea level at local Y=0; no Rigidbody or runtime scripts.");
            }
            finally
            {
                if (existing) PrefabUtility.UnloadPrefabContents(root);
                else Object.DestroyImmediate(root);
            }
        }

        static void BuildGeometry(Transform parent, Material paint, Material tape, Material rubber,
            Material steel, Material rusty, Material housing, Material solar, Material lens)
        {
            var hull = Lathe("FloatHull", new[] {
                P(-.30f, .13f), P(-.28f, .20f), P(-.23f, .29f), P(-.16f, .35f),
                P(-.08f, .377f), P(.02f, .38f), P(.11f, .382f), P(.80f, .38f),
                P(.88f, .36f), P(.94f, .29f), P(.975f, .21f), P(.99f, .20f) });
            Node(parent, "Painted welded float", hull, paint);
            Node(parent, "Retroreflective band", Lathe("ReflectiveBand", new[] {
                P(.675f,.382f), P(.679f,.385f), P(.786f,.385f), P(.79f,.382f) }), tape);
            Node(parent, "Waterline impact belt", Lathe("RubberBelt", new[] {
                P(.09f,.383f), P(.105f,.392f), P(.12f,.395f), P(.205f,.395f),
                P(.22f,.392f), P(.233f,.382f) }), rubber);
            Ring(parent, "Hull seam lower", new Vector3(0,.04f,0), .38f, .004f, paint);
            Ring(parent, "Hull seam upper", new Vector3(0,.84f,0), .375f, .004f, rusty);
            Ring(parent, "Welded shoulder seam", new Vector3(0,.952f,0), .266f, .003f, rusty);

            var unit = Lathe("UnitCylinder", new[] { P(-.5f,1), P(.5f,1) }, 32);
            var hex = Lathe("HexFastener", new[] { P(-.5f,1), P(.5f,1) }, 6);
            var cube = Box();
            Cylinder(parent, "Bolted top flange", unit, housing, new Vector3(0,.997f,0), .203f,.023f);
            Ring(parent, "Flange gasket", new Vector3(0,.982f,0), .202f,.004f,rubber);
            Cylinder(parent, "Orange instrument stem", unit, paint, new Vector3(0,1.105f,0), .057f,.195f);
            for (int i=0; i<8; i++)
            {
                float a=i*Mathf.PI/4;
                Vector3 pos=new Vector3(Mathf.Cos(a)*.166f,1.014f,Mathf.Sin(a)*.166f);
                Cylinder(parent,"Flange bolt "+i,hex,steel,pos,.010f,.008f);
                Ring(parent,"Flange washer "+i,pos-new Vector3(0,.003f,0),.011f,.002f,steel,16,6);
            }

            // Two welded lifting eyes and a submerged mooring attachment, with no Unity simulation.
            for(int side=-1; side<=1; side+=2)
            {
                var basePos=new Vector3(side*.21f,.936f,0);
                var eye=Ring(parent,"Lifting eye "+side,basePos+new Vector3(0,.044f,0),.032f,.007f,steel,32,10);
                eye.transform.localRotation=Quaternion.Euler(90,0,0);
                Tube(parent,"Eye weld "+side,unit,rusty,basePos-new Vector3(.022f,0,0),basePos+new Vector3(.022f,0,0),.007f);
            }
            Cylinder(parent,"Ballast attachment",unit,rusty,new Vector3(0,-.306f,0),.071f,.04f);
            for(int i=0; i<3; i++)
            {
                var link=Ring(parent,"Mooring link "+i,new Vector3(0,-.356f-i*.056f,0),.024f,.006f,rusty,28,8);
                link.transform.localRotation=Quaternion.Euler(90,i%2==0?0:90,0);
                link.transform.localScale=new Vector3(1,1,1.45f);
            }

            // Small four-sided solar array, aluminium frames and visible blue cells.
            for(int i=0; i<4; i++)
            {
                var panel=new GameObject("Solar panel "+i);
                panel.transform.SetParent(parent,false);
                float a=i*Mathf.PI/2;
                panel.transform.localPosition=new Vector3(Mathf.Cos(a)*.129f,1.055f,Mathf.Sin(a)*.129f);
                panel.transform.localRotation=Quaternion.Euler(0,90-i*90,0)*Quaternion.Euler(18,0,0);
                var frame=Node(panel.transform,"Anodized frame",cube,steel);
                frame.transform.localScale=new Vector3(.15f,.008f,.092f);
                var cells=Node(panel.transform,"Solar cell glass",cube,solar);
                cells.transform.localPosition=new Vector3(0,.005f,0);
                cells.transform.localScale=new Vector3(.134f,.003f,.077f);
            }

            Cylinder(parent,"Lantern lower housing",unit,housing,new Vector3(0,1.222f,0),.096f,.037f);
            var lensProfile=new List<Vector2>{P(1.241f,.070f)};
            for(int i=0;i<13;i++)
            {
                float y=1.247f+i*.012f;
                lensProfile.Add(P(y,.084f));
                lensProfile.Add(P(y+.005f,.077f));
                lensProfile.Add(P(y+.010f,.077f));
            }
            lensProfile.Add(P(1.404f,.07f));
            Node(parent,"Ribbed amber lantern lens",Lathe("FresnelLens",lensProfile.ToArray()),lens);
            Cylinder(parent,"Lantern top cap",unit,housing,new Vector3(0,1.424f,0),.092f,.03f);
            Ring(parent,"Cage lower hoop",new Vector3(0,1.235f,0),.11f,.006f,steel,48,8);
            Ring(parent,"Cage upper hoop",new Vector3(0,1.455f,0),.11f,.006f,steel,48,8);
            for(int i=0;i<4;i++)
            {
                float a=i*Mathf.PI/2+Mathf.PI/4;
                Vector3 start=new Vector3(Mathf.Cos(a)*.11f,1.233f,Mathf.Sin(a)*.11f);
                Tube(parent,"Lantern guard "+i,unit,steel,start,start+new Vector3(0,.222f,0),.005f);
                Tube(parent,"Lantern roof strut "+i,unit,steel,start+new Vector3(0,.222f,0),new Vector3(0,1.52f,0),.004f);
            }
            Cylinder(parent,"Roof apex",unit,housing,new Vector3(0,1.524f,0),.018f,.018f);
            Cylinder(parent,"Antenna insulator",unit,housing,new Vector3(.068f,1.15f,-.068f),.012f,.047f);
            Tube(parent,"Short telemetry antenna",unit,steel,new Vector3(.068f,1.17f,-.068f),new Vector3(.068f,1.54f,-.068f),.0028f);
        }

        static Vector2 P(float height,float radius) => new Vector2(radius,height);

        static Mesh Lathe(string name,Vector2[] profile,int segments=Segments)
        {
            var vertices=new List<Vector3>(); var normals=new List<Vector3>();
            var uv=new List<Vector2>(); var indices=new List<int>();
            float min=profile[0].y,max=profile[profile.Length-1].y;
            for(int ring=0;ring<profile.Length;ring++)
            {
                Vector2 tangent=profile[Math.Min(ring+1,profile.Length-1)]-profile[Math.Max(0,ring-1)];
                for(int j=0;j<=segments;j++)
                {
                    float a=2*Mathf.PI*j/segments,cos=Mathf.Cos(a),sin=Mathf.Sin(a);
                    vertices.Add(new Vector3(profile[ring].x*cos,profile[ring].y,profile[ring].x*sin));
                    normals.Add(new Vector3(tangent.y*cos,-tangent.x,tangent.y*sin).normalized);
                    uv.Add(new Vector2((float)j/segments,(profile[ring].y-min)/(max-min)));
                    if(ring<profile.Length-1 && j<segments)
                    {
                        int v=ring*(segments+1)+j,n=v+segments+1;
                        indices.AddRange(new[]{v,n,v+1,v+1,n,n+1});
                    }
                }
            }
            // Independent cap vertices preserve sharp shading at machined edges.
            for(int top=0;top<2;top++)
            {
                Vector2 p=profile[top==0?0:profile.Length-1];
                int start=vertices.Count;
                vertices.Add(new Vector3(0,p.y,0)); normals.Add(top==0?Vector3.down:Vector3.up); uv.Add(new Vector2(.5f,.5f));
                for(int j=0;j<=segments;j++)
                {
                    float a=2*Mathf.PI*j/segments;
                    vertices.Add(new Vector3(p.x*Mathf.Cos(a),p.y,p.x*Mathf.Sin(a)));
                    normals.Add(top==0?Vector3.down:Vector3.up);
                    uv.Add(new Vector2(.5f+.5f*Mathf.Cos(a),.5f+.5f*Mathf.Sin(a)));
                    if(j<segments) indices.AddRange(top==0?new[]{start,start+j+1,start+j+2}:new[]{start,start+j+2,start+j+1});
                }
            }
            return SaveMesh(name,vertices,normals,uv,indices);
        }

        static Mesh Torus(string name,float major,float minor,int rings,int sides)
        {
            var vertices=new List<Vector3>();var normals=new List<Vector3>();
            var uv=new List<Vector2>();var indices=new List<int>();
            for(int i=0;i<=rings;i++) for(int j=0;j<=sides;j++)
            {
                float a=i*2*Mathf.PI/rings,b=j*2*Mathf.PI/sides;
                float ca=Mathf.Cos(a),sa=Mathf.Sin(a),cb=Mathf.Cos(b),sb=Mathf.Sin(b);
                vertices.Add(new Vector3((major+minor*cb)*ca,minor*sb,(major+minor*cb)*sa));
                normals.Add(new Vector3(cb*ca,sb,cb*sa));uv.Add(new Vector2((float)i/rings,(float)j/sides));
                if(i<rings && j<sides)
                {
                    int v=i*(sides+1)+j,n=v+sides+1;
                    indices.AddRange(new[]{v,v+1,n,v+1,n+1,n});
                }
            }
            return SaveMesh(name,vertices,normals,uv,indices);
        }

        static Mesh Box()
        {
            var vertices=new List<Vector3>();var normals=new List<Vector3>();
            var uv=new List<Vector2>();var triangles=new List<int>();
            foreach(var n in new[]{Vector3.up,Vector3.down,Vector3.forward,Vector3.back,Vector3.right,Vector3.left})
            {
                Vector3 right=Vector3.Cross(Mathf.Abs(n.y)>.5f?Vector3.forward:Vector3.up,n).normalized;
                Vector3 up=Vector3.Cross(n,right);int start=vertices.Count;
                vertices.AddRange(new[]{(n-right-up)*.5f,(n+right-up)*.5f,(n+right+up)*.5f,(n-right+up)*.5f});
                for(int i=0;i<4;i++) normals.Add(n);
                uv.AddRange(new[]{Vector2.zero,Vector2.right,Vector2.one,Vector2.up});
                triangles.AddRange(new[]{start,start+1,start+2,start,start+2,start+3});
            }
            return SaveMesh("EquipmentBox",vertices,normals,uv,triangles);
        }

        static Mesh SaveMesh(string name,List<Vector3> vertices,List<Vector3> normals,List<Vector2> uv,List<int> indices)
        {
            var mesh=new Mesh{name=name,indexFormat=IndexFormat.UInt32};
            mesh.SetVertices(vertices);mesh.SetNormals(normals);mesh.SetUVs(0,uv);mesh.SetTriangles(indices,0);
            mesh.RecalculateBounds();mesh.RecalculateTangents();
            return PersistMesh(name,mesh);
        }

        static Mesh PersistMesh(string name,Mesh mesh)
        {
            string path=AssetRoot+"/Meshes/"+name+".asset";
            var existing=AssetDatabase.LoadAssetAtPath<Mesh>(path);
            if(existing==null) { AssetDatabase.CreateAsset(mesh,path);return mesh; }
            EditorUtility.CopySerialized(mesh,existing);Object.DestroyImmediate(mesh);EditorUtility.SetDirty(existing);return existing;
        }

        static GameObject Node(Transform parent,string name,Mesh mesh,Material material)
        {
            var go=new GameObject(name);go.transform.SetParent(parent,false);
            go.AddComponent<MeshFilter>().sharedMesh=mesh;
            var renderer=go.AddComponent<MeshRenderer>();renderer.sharedMaterial=material;
            renderer.shadowCastingMode=ShadowCastingMode.On;renderer.receiveShadows=true;
            return go;
        }

        static void Cylinder(Transform parent,string name,Mesh mesh,Material material,Vector3 position,float radius,float height)
        {
            var go=Node(parent,name,mesh,material);go.transform.localPosition=position;
            go.transform.localScale=new Vector3(radius,height,radius);
        }

        static void Tube(Transform parent,string name,Mesh mesh,Material material,Vector3 start,Vector3 end,float radius)
        {
            var go=Node(parent,name,mesh,material);go.transform.localPosition=(start+end)*.5f;
            go.transform.localRotation=Quaternion.FromToRotation(Vector3.up,end-start);
            go.transform.localScale=new Vector3(radius,(end-start).magnitude,radius);
        }

        static GameObject Ring(Transform parent,string name,Vector3 position,float major,float minor,Material material,int rings=64,int sides=10)
        {
            string key="Ring_"+major.ToString("F4",System.Globalization.CultureInfo.InvariantCulture).Replace('.','_')+
                "_"+minor.ToString("F4",System.Globalization.CultureInfo.InvariantCulture).Replace('.','_')+"_"+rings+"_"+sides;
            var go=Node(parent,name,Torus(key,major,minor,rings,sides),material);go.transform.localPosition=position;return go;
        }

        static void CombineByMaterial(Transform parent)
        {
            // One renderer per material, not one draw call for every individual bolt.
            var renderers=parent.GetComponentsInChildren<MeshRenderer>();
            var materials=renderers.Select(renderer=>renderer.sharedMaterial).Distinct().ToArray();
            foreach(var group in renderers.GroupBy(renderer=>renderer.sharedMaterial))
            {
                var instances=group.Select(renderer=>new CombineInstance{
                    mesh=renderer.GetComponent<MeshFilter>().sharedMesh,
                    transform=parent.worldToLocalMatrix*renderer.transform.localToWorldMatrix
                }).ToArray();
                var combined=new Mesh{name="Combined_"+group.Key.name,indexFormat=IndexFormat.UInt32};
                combined.CombineMeshes(instances,true,true);combined.RecalculateBounds();
                PersistMesh(combined.name,combined);
            }
            foreach(Transform child in parent.Cast<Transform>().ToArray()) Object.DestroyImmediate(child.gameObject);
            foreach(var material in materials)
                Node(parent,material.name,AssetDatabase.LoadAssetAtPath<Mesh>(AssetRoot+"/Meshes/Combined_"+material.name+".asset"),material);
        }

        static Material Material(string name,Color color,float metallic,float smoothness)
        {
            string path=AssetRoot+"/Materials/"+name+".mat";
            var mat=AssetDatabase.LoadAssetAtPath<Material>(path);
            if(mat==null) {mat=new Material(Shader.Find("HDRP/Lit")){name=name};AssetDatabase.CreateAsset(mat,path);}
            mat.SetColor("_BaseColor",color);mat.SetFloat("_Metallic",metallic);mat.SetFloat("_Smoothness",smoothness);
            mat.SetFloat("_SurfaceType",0);mat.SetFloat("_AlphaCutoffEnable",0);
            mat.SetFloat("_DoubleSidedEnable",0);mat.enableInstancing=true;
            HDMaterial.ValidateMaterial(mat);EditorUtility.SetDirty(mat);return mat;
        }

        static Texture2D[] CreateWeatheredMaps()
        {
            var albedo=new Color32[TextureSize*TextureSize];var mask=new Color32[albedo.Length];
            var normal=new Color32[albedo.Length];var heights=new float[albedo.Length];
            var orange=new Color(.82f,.22f,.035f);var rust=new Color(.24f,.095f,.029f);
            for(int y=0;y<TextureSize;y++) for(int x=0;x<TextureSize;x++)
            {
                float u=(float)x/TextureSize,v=(float)y/(TextureSize-1);
                float cloud=PeriodicNoise(u,v,4,4),grain=PeriodicNoise(u,v,115,61);
                float streak=PeriodicNoise(u,v,48,2),chips=PeriodicNoise(u,v,42,37);
                float line=.255f+.01f*Mathf.Sin(u*2*Mathf.PI*7)+.014f*(cloud-.5f);
                float growth=(1-Smooth(line-.10f,line+.015f,v))*(.30f+cloud*.6f);
                float chipAmount=Smooth(.68f,.84f,chips)*(1-Smooth(.42f,.65f,grain));
                float edge=Mathf.Exp(-Mathf.Abs(v-.30f)*85)+Mathf.Exp(-Mathf.Abs(v-.88f)*85);
                chipAmount=Mathf.Clamp01(chipAmount*.62f+edge*Smooth(.48f,.78f,chips)*.65f);
                Color color=orange*(.80f+.30f*cloud+.045f*(grain-.5f));
                color=Color.Lerp(color,new Color(.58f,.40f,.22f),Smooth(.56f,.90f,streak)*.16f);
                color=Color.Lerp(color,rust,chipAmount);
                color=Color.Lerp(color,new Color(.095f,.12f,.068f),growth*.80f);
                float salt=Mathf.Exp(-Mathf.Abs(v-line-.025f)*80)*(.3f+.7f*grain);
                color=Color.Lerp(color,new Color(.68f,.64f,.49f),salt*.35f);
                if(IsSerialPaint(u,v)) color=Color.Lerp(color,new Color(.82f,.79f,.68f),.83f+.12f*grain);
                int p=y*TextureSize+x;albedo[p]=color;
                float wet=(1-Smooth(line-.02f,line+.02f,v))*.35f;
                mask[p]=new Color(.08f+chipAmount*.35f,.92f-chipAmount*.20f,1,.29f+wet-chipAmount*.12f);
                heights[p]=grain*.15f+chipAmount*.25f+growth*.12f;
            }
            for(int y=0;y<TextureSize;y++) for(int x=0;x<TextureSize;x++)
            {
                int left=y*TextureSize+(x+TextureSize-1)%TextureSize,right=y*TextureSize+(x+1)%TextureSize;
                int down=Math.Max(0,y-1)*TextureSize+x,up=Math.Min(TextureSize-1,y+1)*TextureSize+x;
                Vector3 n=new Vector3((heights[left]-heights[right])*1.4f,(heights[down]-heights[up])*1.4f,1).normalized;
                normal[y*TextureSize+x]=new Color(n.x*.5f+.5f,n.y*.5f+.5f,n.z*.5f+.5f,1);
            }
            return new[]{SaveTexture("OrangeSaltRust_BaseColor",albedo,false,false),
                SaveTexture("OrangeSaltRust_Mask",mask,true,false),SaveTexture("OrangeSaltRust_Normal",normal,true,true)};
        }

        static float Smooth(float low,float high,float value) => Mathf.SmoothStep(0,1,Mathf.InverseLerp(low,high,value));

        static float PeriodicNoise(float u,float v,float around,float vertical)
        {
            float angle=u*2*Mathf.PI;
            return Mathf.PerlinNoise(18.31f+Mathf.Cos(angle)*around+v*vertical,
                27.17f+Mathf.Sin(angle)*around+v*vertical*.731f);
        }

        static bool IsSerialPaint(float u,float v)
        {
            if(v<.565f || v>=.619f) return false;
            float horizontal=Mathf.Repeat(u-.175f,.5f);
            if(horizontal>=.15f) return false;
            int cell=(int)(horizontal/.005f),letter=cell/6,col=cell%6;
            if(letter>=5 || col==5) return false;
            int row=Mathf.Clamp(6-(int)((v-.565f)/(.054f/7)),0,6);
            int[][] glyphs={new[]{17,27,21,21,17,17,17},new[]{30,17,17,30,17,17,30},
                new[]{0,0,0,31,0,0,0},new[]{14,17,19,21,25,17,14},new[]{4,12,4,4,4,4,14}};
            return (glyphs[letter][row]&(1<<(4-col)))!=0;
        }

        static Texture2D CreateSolarTexture()
        {
            const int size=256;var colors=new Color32[size*size];
            for(int y=0;y<size;y++) for(int x=0;x<size;x++)
            {
                bool grid=x%64<2 || y%64<2;bool bus=x%64==21 || x%64==42;
                float sheen=.9f+.10f*Mathf.PerlinNoise(x*.06f,y*.06f);
                colors[y*size+x]=grid?new Color(.31f,.35f,.38f):bus?new Color(.35f,.43f,.51f):new Color(.025f,.065f,.13f)*sheen;
            }
            return SaveTexture("SolarCells_BaseColor",colors,false,false,size);
        }

        static Texture2D SaveTexture(string name,Color32[] pixels,bool linear,bool normal,int size=TextureSize)
        {
            string path=AssetRoot+"/Textures/"+name+".png";
            var texture=new Texture2D(size,size,TextureFormat.RGBA32,false,linear);
            texture.SetPixels32(pixels);texture.Apply();File.WriteAllBytes(path,texture.EncodeToPNG());Object.DestroyImmediate(texture);
            AssetDatabase.ImportAsset(path,ImportAssetOptions.ForceSynchronousImport);
            var importer=(TextureImporter)AssetImporter.GetAtPath(path);
            importer.textureType=normal?TextureImporterType.NormalMap:TextureImporterType.Default;
            importer.sRGBTexture=!linear;importer.mipmapEnabled=true;importer.wrapMode=TextureWrapMode.Repeat;
            importer.filterMode=FilterMode.Trilinear;importer.anisoLevel=4;importer.maxTextureSize=size;
            importer.textureCompression=TextureImporterCompression.Uncompressed;importer.SaveAndReimport();
            return AssetDatabase.LoadAssetAtPath<Texture2D>(path);
        }

        static void RegisterAddress()
        {
            var settings=AddressableAssetSettingsDefaultObject.Settings;
            if(settings==null) throw new InvalidOperationException("Existing Addressables settings were not found.");
            var group=settings.FindGroup("SpawnInterface") ?? settings.DefaultGroup;
            string guid=AssetDatabase.AssetPathToGUID(PrefabPath);
            foreach(var candidate in settings.groups.Where(g=>g!=null).SelectMany(g=>g.entries))
                if(candidate.address=="buoy" && candidate.guid!=guid)
                    throw new InvalidOperationException("Another asset already uses 'buoy'; it has not been overwritten.");
            var entry=settings.CreateOrMoveEntry(guid,group);entry.address="buoy";
            settings.SetDirty(AddressableAssetSettings.ModificationEvent.EntryModified,entry,true,true);
            EditorUtility.SetDirty(group);
        }

        static void Validate(GameObject prefab)
        {
            int triangles=0;var renderers=prefab.GetComponentsInChildren<MeshRenderer>();
            if(renderers.Length==0) throw new InvalidOperationException("The buoy has no visible meshes.");
            foreach(var renderer in renderers)
            {
                var mesh=renderer.GetComponent<MeshFilter>().sharedMesh;
                if(mesh==null || mesh.vertexCount==0 || mesh.normals.Length!=mesh.vertexCount || mesh.uv.Length!=mesh.vertexCount)
                    throw new InvalidOperationException("Invalid mesh on "+renderer.name);
                if(mesh.vertices.Any(v=>float.IsNaN(v.x)||float.IsInfinity(v.x)||float.IsNaN(v.y)||float.IsInfinity(v.y)||float.IsNaN(v.z)||float.IsInfinity(v.z)))
                    throw new InvalidOperationException("Non-finite vertex on "+renderer.name);
                if(mesh.triangles.Any(i=>i<0 || i>=mesh.vertexCount)) throw new InvalidOperationException("Invalid triangle index.");
                if(renderer.sharedMaterial==null || renderer.sharedMaterial.shader.name!="HDRP/Lit")
                    throw new InvalidOperationException("Invalid HDRP material on "+renderer.name);
                triangles+=mesh.triangles.Length/3;
            }
            if(prefab.GetComponentsInChildren<Rigidbody>().Length!=0) throw new InvalidOperationException("Unexpected Unity Rigidbody.");
            string directory="artifacts/buoy";Directory.CreateDirectory(directory);
            File.WriteAllText(directory+"/validation.txt","Prefab: "+PrefabPath+"\nAddress: buoy\nRenderers: "+renderers.Length+
                "\nTriangles: "+triangles+"\nHDRP materials and finite meshes: OK\nNo Unity Rigidbody: OK\nPrefab GUID: "+AssetDatabase.AssetPathToGUID(PrefabPath)+"\n");
        }

        [MenuItem("LOTUSim/Models/Preview realistic buoy")]
        public static void Preview()
        {
            var prefab=AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath);
            if(prefab==null) return;
            QueuePreview(prefab);
        }

        static void QueuePreview(GameObject prefab)
        {
            // AssetPreview uses Unity's own HDRP prefab renderer, not an invented reference image.
            int tries=0;bool largeAttempted=false;EditorApplication.CallbackFunction update=null;
            update=()=>{
                if(EditorApplication.isCompiling || EditorApplication.isPlayingOrWillChangePlaymode) return;
                if(!largeAttempted)
                {
                    largeAttempted=true;
                    TryLargePreview(prefab);
                }
                var preview=AssetPreview.GetAssetPreview(prefab);
                if(preview!=null)
                {
                    Directory.CreateDirectory("artifacts/buoy");
                    File.WriteAllBytes("artifacts/buoy/preview.png",preview.EncodeToPNG());
                    EditorApplication.update-=update;
                    Debug.Log("[MarineBuoyBuilder] Actual Unity prefab preview saved: artifacts/buoy/preview.png");
                }
                else if(++tries>1200) EditorApplication.update-=update;
            };
            EditorApplication.update+=update;
        }

        static void TryLargePreview(GameObject prefab)
        {
            if(SystemInfo.graphicsDeviceType==GraphicsDeviceType.Null) return;
            UnityEditor.Editor inspector=null;Texture2D texture=null;
            try
            {
                inspector=UnityEditor.Editor.CreateEditor(prefab);
                texture=inspector.RenderStaticPreview(PrefabPath,null,768,768);
                if(texture==null || texture.width<512) return;
                Directory.CreateDirectory("artifacts/buoy");
                File.WriteAllBytes("artifacts/buoy/preview-large.png",texture.EncodeToPNG());
                Debug.Log("[MarineBuoyBuilder] High-resolution Unity preview saved: artifacts/buoy/preview-large.png");
            }
            catch(Exception exception)
            {
                Debug.LogWarning("[MarineBuoyBuilder] Large preview unavailable; standard preview retained: "+exception.Message);
            }
            finally
            {
                if(texture!=null) Object.DestroyImmediate(texture);
                if(inspector!=null) Object.DestroyImmediate(inspector);
            }
        }

        static void EnsureFolder(string path)
        {
            if(AssetDatabase.IsValidFolder(path)) return;
            string parent=Path.GetDirectoryName(path).Replace('\\','/');
            EnsureFolder(parent);AssetDatabase.CreateFolder(parent,Path.GetFileName(path));
        }
    }
}
