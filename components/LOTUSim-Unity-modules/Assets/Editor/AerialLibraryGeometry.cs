using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using Object=UnityEngine.Object;

namespace Lotusim.EditorTools
{
    public static partial class AerialLibraryBuilder
    {
        sealed class MeshData
        {
            public readonly List<Vector3> vertices=new List<Vector3>();
            public readonly List<Vector3> normals=new List<Vector3>();
            public readonly List<Vector2> uv=new List<Vector2>();
            public readonly List<int>[] faces;
            public MeshData(int materials=1) { faces=Enumerable.Range(0,materials).Select(_=>new List<int>()).ToArray(); }
            public int V(Vector3 point,Vector2 tex,Vector3 normal=default(Vector3)) {
                int index=vertices.Count;vertices.Add(point);uv.Add(tex);normals.Add(normal);return index;
            }
            public void F(int a,int b,int c,int material=0) { faces[material].AddRange(new[]{a,b,c}); }
            public void Outward(int a,int b,int c,Vector3 expected,int material=0) {
                if(Vector3.Dot(Vector3.Cross(vertices[b]-vertices[a],vertices[c]-vertices[a]),expected)<0) F(a,c,b,material);
                else F(a,b,c,material);
            }
        }

        // Section: radii X/Y, longitudinal Z, vertical centre. No negative transform scales.
        static Vector4 S(float z,float rx,float ry,float centreY=0) => new Vector4(rx,ry,z,centreY);

        static Mesh Loft(string name,Vector4[] sections,int around=64,int materials=1,Func<float,float,int> selector=null)
        {
            return SaveMesh(name,LoftData(sections,around,materials,selector));
        }

        static MeshData LoftData(Vector4[] sections,int around,int materials,Func<float,float,int> selector)
        {
            var data=new MeshData(materials);float minZ=sections[0].z,maxZ=sections[sections.Length-1].z;
            for(int k=0;k<sections.Length;k++) {
                var p=sections[k];var tangent=sections[Math.Min(k+1,sections.Length-1)]-sections[Math.Max(0,k-1)];
                for(int j=0;j<=around;j++) {
                    float a=j*2*Mathf.PI/around,c=Mathf.Cos(a),s=Mathf.Sin(a);
                    float nx=c/p.x,ny=s/p.y;
                    float nz=-(nx*tangent.x*c+ny*(tangent.w+tangent.y*s))/tangent.z;
                    data.V(new Vector3(p.x*c,p.w+p.y*s,p.z),new Vector2((float)j/around,(p.z-minZ)/(maxZ-minZ)),new Vector3(nx,ny,nz).normalized);
                }
            }
            // Winding checks require every referenced vertex to exist already.
            for(int k=0;k<sections.Length-1;k++) for(int j=0;j<around;j++) {
                int v=k*(around+1)+j,n=v+around+1;
                int material=selector==null?0:selector((sections[k].z+sections[k+1].z)*.5f,(j+.5f)*2*Mathf.PI/around);
                data.F(v,v+1,n,material);data.F(v+1,n+1,n,material);
            }
            for(int end=0;end<2;end++) {
                var p=sections[end==0?0:sections.Length-1];int start=data.vertices.Count;
                Vector3 normal=end==0?Vector3.back:Vector3.forward;
                data.V(new Vector3(0,p.w,p.z),new Vector2(.5f,.5f),normal);
                for(int j=0;j<=around;j++) {
                    float a=j*2*Mathf.PI/around;
                    data.V(new Vector3(p.x*Mathf.Cos(a),p.w+p.y*Mathf.Sin(a),p.z),new Vector2(.5f+.5f*Mathf.Cos(a),.5f+.5f*Mathf.Sin(a)),normal);
                }
                for(int j=0;j<around;j++) data.Outward(start,start+j+1,start+j+2,normal);
            }
            return data;
        }

        // Airfoil stations: span X, height Y, chord centre Z, chord length.
        static Mesh Wing(string name,Vector4[] stations,float thickness=.12f,float camber=.02f,int side=1,int materials=1,Func<float,float,int> selector=null)
        {
            return SaveMesh(name,WingData(stations,thickness,camber,side,materials,selector));
        }

        static MeshData WingData(Vector4[] stations,float thickness,float camber,int side,int materials,Func<float,float,int> selector)
        {
            const int ring=64;var data=new MeshData(materials);
            for(int i=0;i<stations.Length;i++) for(int j=0;j<=ring;j++) {
                var p=stations[i];float angle=j*2*Mathf.PI/ring,t=(1-Mathf.Cos(angle))*.5f;
                float section=5*thickness*(.2969f*Mathf.Sqrt(t)-.1260f*t-.3516f*t*t+.2843f*t*t*t-.1036f*t*t*t*t)*p.w;
                float sign=j<=ring/2?1:-1;
                data.V(new Vector3(side*p.x,p.y+camber*p.w*Mathf.Sin(Mathf.PI*t)+sign*section,p.z+(.5f-t)*p.w),
                    new Vector2(t,p.x/stations[stations.Length-1].x));
            }
            for(int i=0;i<stations.Length-1;i++) for(int j=0;j<ring;j++) {
                int v=i*(ring+1)+j,n=v+ring+1;
                float span=(stations[i].x+stations[i+1].x)*.5f;
                int material=selector==null?0:selector(span,(j+.5f)*2*Mathf.PI/ring);
                Vector3 expected=(j+.5f)<ring/2?Vector3.up:Vector3.down;
                data.Outward(v,n,v+1,expected,material);data.Outward(v+1,n,n+1,expected,material);
            }
            for(int end=0;end<2;end++) {
                var p=stations[end==0?0:stations.Length-1];int first=data.vertices.Count;
                data.V(new Vector3(side*p.x,p.y,p.z),new Vector2(.5f,.5f));
                for(int j=0;j<=ring;j++) {
                    int original=(end==0?0:stations.Length-1)*(ring+1)+j;
                    data.V(data.vertices[original],data.uv[original]);
                }
                for(int j=0;j<ring;j++) data.Outward(first,first+j+1,first+j+2,(end==0?-side:side)*Vector3.right);
            }
            return data;
        }

        static Mesh UnitSphere()
        {
            var existing=AssetDatabase.LoadAssetAtPath<Mesh>(meshDirectory+"/UnitSphere.asset");if(existing!=null) return existing;
            var sections=new List<Vector4>();
            for(int i=0;i<=24;i++) {
                float a=-Mathf.PI*.5f+i*Mathf.PI/24;float r=Mathf.Max(.0001f,Mathf.Cos(a));
                sections.Add(S(Mathf.Sin(a),r,r));
            }
            return Loft("UnitSphere",sections.ToArray(),40);
        }

        static Mesh UnitCylinder()
        {
            var existing=AssetDatabase.LoadAssetAtPath<Mesh>(meshDirectory+"/UnitCylinder.asset");
            return existing!=null?existing:Loft("UnitCylinder",new[]{S(-.5f,1,1),S(.5f,1,1)},32);
        }

        static Mesh UnitBox()
        {
            var existing=AssetDatabase.LoadAssetAtPath<Mesh>(meshDirectory+"/UnitBox.asset");if(existing!=null) return existing;
            var data=new MeshData();
            foreach(var n in new[]{Vector3.up,Vector3.down,Vector3.left,Vector3.right,Vector3.forward,Vector3.back}) {
                Vector3 right=Vector3.Cross(Mathf.Abs(n.y)>.5f?Vector3.forward:Vector3.up,n).normalized;
                Vector3 up=Vector3.Cross(n,right);int first=data.vertices.Count;
                data.V((n-right-up)*.5f,Vector2.zero,n);data.V((n+right-up)*.5f,Vector2.right,n);
                data.V((n+right+up)*.5f,Vector2.one,n);data.V((n-right+up)*.5f,Vector2.up,n);
                data.F(first,first+1,first+2);data.F(first,first+2,first+3);
            }
            return SaveMesh("UnitBox",data);
        }

        static Mesh RingMesh(string name,float major,float minor)
        {
            const int rings=48,sides=12;var data=new MeshData();
            for(int i=0;i<=rings;i++) for(int j=0;j<=sides;j++) {
                float a=i*2*Mathf.PI/rings,b=j*2*Mathf.PI/sides;
                float ca=Mathf.Cos(a),sa=Mathf.Sin(a),cb=Mathf.Cos(b),sb=Mathf.Sin(b);
                data.V(new Vector3((major+minor*cb)*ca,minor*sb,(major+minor*cb)*sa),new Vector2((float)i/rings,(float)j/sides),new Vector3(cb*ca,sb,cb*sa));
                if(i<rings && j<sides) {
                    int v=i*(sides+1)+j,n=v+sides+1;data.F(v,v+1,n);data.F(v+1,n+1,n);
                }
            }
            return SaveMesh(name,data);
        }

        static Mesh SaveMesh(string name,MeshData data)
        {
            var mesh=new Mesh{name=name,indexFormat=IndexFormat.UInt32};
            mesh.SetVertices(data.vertices);mesh.SetUVs(0,data.uv);mesh.subMeshCount=data.faces.Length;
            for(int i=0;i<data.faces.Length;i++) mesh.SetTriangles(data.faces[i],i);
            if(data.normals.Any(n=>n.sqrMagnitude<.5f)) mesh.RecalculateNormals();else mesh.SetNormals(data.normals);
            mesh.RecalculateBounds();mesh.RecalculateTangents();return Persist(name,mesh);
        }

        static Mesh Persist(string name,Mesh mesh)
        {
            string path=meshDirectory+"/"+name+".asset";var existing=AssetDatabase.LoadAssetAtPath<Mesh>(path);
            if(existing==null) {AssetDatabase.CreateAsset(mesh,path);return mesh;}
            EditorUtility.CopySerialized(mesh,existing);Object.DestroyImmediate(mesh);EditorUtility.SetDirty(existing);return existing;
        }

        static GameObject Add(Transform parent,string name,Mesh mesh,Material[] materials,Vector3 position=default(Vector3))
        {
            var go=new GameObject(name);go.transform.SetParent(parent,false);go.transform.localPosition=position;
            go.AddComponent<MeshFilter>().sharedMesh=mesh;
            var renderer=go.AddComponent<MeshRenderer>();renderer.sharedMaterials=materials;renderer.receiveShadows=true;
            renderer.shadowCastingMode=ShadowCastingMode.On;return go;
        }
        static GameObject Add(Transform parent,string name,Mesh mesh,Material material,Vector3 position=default(Vector3)) => Add(parent,name,mesh,new[]{material},position);
        static GameObject Ellipsoid(Transform parent,string name,Vector3 position,Vector3 radii,Material material)
        {
            var go=Add(parent,name,UnitSphere(),material,position);go.transform.localScale=radii;return go;
        }
        static GameObject Box(Transform parent,string name,Vector3 position,Vector3 dimensions,Material material,Quaternion? rotation=null)
        {
            var go=Add(parent,name,UnitBox(),material,position);go.transform.localScale=dimensions;
            if(rotation.HasValue) go.transform.localRotation=rotation.Value;return go;
        }
        static GameObject Tube(Transform parent,string name,Vector3 a,Vector3 b,float radius,Material material,float oval=1)
        {
            var go=Add(parent,name,UnitCylinder(),material,(a+b)*.5f);
            go.transform.localRotation=Quaternion.FromToRotation(Vector3.forward,b-a);
            go.transform.localScale=new Vector3(radius,radius*oval,(b-a).magnitude);return go;
        }

        static void CombineMaterials(Transform parent)
        {
            var batches=new Dictionary<Material,List<CombineInstance>>();
            foreach(var renderer in parent.GetComponentsInChildren<MeshRenderer>()) {
                var mesh=renderer.GetComponent<MeshFilter>().sharedMesh;
                for(int sub=0;sub<mesh.subMeshCount;sub++) {
                    if(mesh.GetIndexCount(sub)==0) continue;
                    var material=renderer.sharedMaterials[sub];
                    if(!batches.ContainsKey(material)) batches[material]=new List<CombineInstance>();
                    batches[material].Add(new CombineInstance{mesh=mesh,subMeshIndex=sub,transform=parent.worldToLocalMatrix*renderer.transform.localToWorldMatrix});
                }
            }
            var saved=new Dictionary<Material,Mesh>();
            foreach(var batch in batches) {
                var mesh=new Mesh{name="Combined_"+batch.Key.name,indexFormat=IndexFormat.UInt32};
                mesh.CombineMeshes(batch.Value.ToArray(),true,true);mesh.RecalculateBounds();saved[batch.Key]=Persist(mesh.name,mesh);
            }
            foreach(Transform child in parent.Cast<Transform>().ToArray()) Object.DestroyImmediate(child.gameObject);
            foreach(var batch in saved) Add(parent,batch.Key.name,batch.Value,batch.Key);
        }
    }
}
