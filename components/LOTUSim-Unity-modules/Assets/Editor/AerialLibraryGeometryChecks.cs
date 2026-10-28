using System;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace Lotusim.EditorTools
{
    public static partial class AerialLibraryBuilder
    {
        [MenuItem("LOTUSim/Models/Validate aerial geometry")]
        public static void ValidateGeometry()
        {
            Debug.Log("[AerialLibrary] Geometry regression checks passed: "+CheckGeometryRegression());
        }

        // Tests the actual vertex/triangle algorithms, without creating or replacing assets.
        static int CheckGeometryRegression()
        {
            int checks=0;
            foreach(int sections in new[]{2,4}) foreach(int around in new[]{3,8,32,64}) {
                var profile=Enumerable.Range(0,sections).Select(i=>S(i*.5f,.4f+i*.03f,.2f+i*.02f,i*.01f)).ToArray();
                var data=LoftData(profile,around,3,(z,a)=>(int)(a/(2*Mathf.PI)*3));
                CheckMeshData(data,sections*(around+1)+2*(around+2),2*sections*around,"loft");
                foreach(var faces in data.faces) for(int i=0;i<faces.Count;i+=3) {
                    int a=faces[i],b=faces[i+1],c=faces[i+2];
                    CheckWinding(data,a,b,c,data.normals[a]+data.normals[b]+data.normals[c],"loft");
                }
                checks++;
            }
            foreach(int side in new[]{-1,1}) foreach(int sections in new[]{2,4}) foreach(float thickness in new[]{.035f,.12f}) {
                const int ring=64;
                var profile=Enumerable.Range(0,sections).Select(i=>new Vector4(.2f+i*.5f,i*.03f,-i*.04f,.6f-i*.04f)).ToArray();
                var data=WingData(profile,thickness,.02f,side,3,(span,a)=>(int)(a/(2*Mathf.PI)*3));
                CheckMeshData(data,sections*(ring+1)+2*(ring+2),2*sections*ring,"wing");
                for(int station=0;station<sections-1;station++) for(int segment=0;segment<ring;segment++) {
                    int v=station*(ring+1)+segment,n=v+ring+1;
                    Vector3 expected=segment<ring/2?Vector3.up:Vector3.down;
                    // Find the two stored faces independent of their material and winding.
                    foreach(var faces in data.faces) for(int i=0;i<faces.Count;i+=3) {
                        int a=faces[i],b=faces[i+1],c=faces[i+2];
                        if(new[]{a,b,c}.All(index=>index==v||index==v+1||index==n||index==n+1))
                            CheckWinding(data,a,b,c,expected,"wing");
                    }
                }
                int capStart=sections*(ring+1);
                for(int end=0;end<2;end++) foreach(var faces in data.faces) for(int i=0;i<faces.Count;i+=3) {
                    int a=faces[i],b=faces[i+1],c=faces[i+2];
                    if(a==capStart+end*(ring+2)) CheckWinding(data,a,b,c,(end==0?-side:side)*Vector3.right,"wing cap");
                }
                checks++;
            }
            return checks;
        }

        static void CheckMeshData(MeshData data,int vertices,int triangles,string label)
        {
            if(data.vertices.Count!=vertices || data.normals.Count!=vertices || data.uv.Count!=vertices ||
                data.faces.Sum(f=>f.Count)!=triangles*3 || data.faces.Any(f=>f.Count%3!=0 || f.Any(i=>i<0||i>=vertices)))
                throw new InvalidOperationException("Invalid geometry topology: "+label);
            if(data.vertices.Concat(data.normals).Any(v=>!FiniteComponent(v.x)||!FiniteComponent(v.y)||!FiniteComponent(v.z)) ||
                data.uv.Any(v=>!FiniteComponent(v.x)||!FiniteComponent(v.y)))
                throw new InvalidOperationException("Non-finite geometry attributes: "+label);
        }

        static bool FiniteComponent(float value) => !float.IsNaN(value)&&!float.IsInfinity(value);

        static void CheckWinding(MeshData data,int a,int b,int c,Vector3 expected,string label)
        {
            if(Vector3.Dot(Vector3.Cross(data.vertices[b]-data.vertices[a],data.vertices[c]-data.vertices[a]),expected)<-1e-7f)
                throw new InvalidOperationException("Inverted face: "+label);
        }
    }
}
