using System;
using UnityEngine;
using UnityEngine.Experimental.Rendering;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace Lotusim.Dataset
{
    [Serializable] public sealed class DatasetMaskTarget {public MeshRenderer[] renderers;}
    [Serializable] public sealed class DatasetMultiInstanceMaskPass : CustomPass
    {
        [NonSerialized] public Camera camera;
        [NonSerialized] public DatasetMaskTarget[] targets=Array.Empty<DatasetMaskTarget>();
        // Scope information only: the observer is deliberately NOT a target
        // slot and never becomes an annotated/category-bearing instance.
        [NonSerialized] public MeshRenderer[] observerRenderers=Array.Empty<MeshRenderer>();
        [NonSerialized] public int width,height,capacity;
        [NonSerialized] public bool armed;
        public int Frame {get;private set;}=-1;
        public string Error {get;private set;}
        public RTHandle[] Visible {get;private set;}
        public RTHandle[] Amodal {get;private set;}
        public RTHandle ObserverVisible {get;private set;}
        Material material;
        DatasetMaskTarget observerTarget;
        protected override bool executeInSceneView=>false;
        protected override void Setup(ScriptableRenderContext context,CommandBuffer cmd)
        {
            var shader=Resources.Load<Shader>("Dataset/InstanceMask");
            if(shader==null||!shader.isSupported) {Error="Sequence instance-mask shader unavailable.";return;}
            material=CoreUtils.CreateEngineMaterial(shader);Visible=new RTHandle[capacity];Amodal=new RTHandle[capacity];
            // Single-channel binary masks limit 4K GPU memory. Retain a portable
            // RGBA fallback on devices without renderable R8 targets.
            var format=SystemInfo.IsFormatSupported(GraphicsFormat.R8_UNorm,FormatUsage.Render)?GraphicsFormat.R8_UNorm:GraphicsFormat.R8G8B8A8_UNorm;
            for(int i=0;i<capacity;i++) {
                Visible[i]=RTHandles.Alloc(width,height,colorFormat:format,useDynamicScale:false,name:"Sequence visible "+i);
                Amodal[i]=RTHandles.Alloc(width,height,colorFormat:format,useDynamicScale:false,name:"Sequence amodal "+i);
            }
            if(observerRenderers!=null&&observerRenderers.Length>0) {
                observerTarget=new DatasetMaskTarget{renderers=observerRenderers};
                ObserverVisible=RTHandles.Alloc(width,height,colorFormat:format,useDynamicScale:false,name:"Sequence visible observer exclusion");
            }
        }
        protected override void Execute(CustomPassContext ctx)
        {
            if(!armed||ctx.hdCamera.camera!=camera||Error!=null) return;
            try {
                if(ctx.hdCamera.actualWidth!=width||ctx.hdCamera.actualHeight!=height||targets.Length>capacity) throw new InvalidOperationException("Sequence mask dimensions/capacity mismatch.");
                if(observerTarget!=null) {
                    // Use the SAME frozen RGB camera depth. An actual target
                    // in front of the observer fails this ownship depth test
                    // and is not hidden by the exclusion. ZWrite stays off.
                    CoreUtils.SetRenderTarget(ctx.cmd,ObserverVisible,ctx.cameraDepthBuffer,ClearFlag.Color,Color.black);
                    Draw(ctx.cmd,observerTarget,0);
                }
                for(int i=0;i<targets.Length;i++) {
                    CoreUtils.SetRenderTarget(ctx.cmd,Visible[i],ctx.cameraDepthBuffer,ClearFlag.Color,Color.black);Draw(ctx.cmd,targets[i],0);
                    CoreUtils.SetRenderTarget(ctx.cmd,Amodal[i],ClearFlag.Color,Color.black);Draw(ctx.cmd,targets[i],1);
                }
                CoreUtils.SetRenderTarget(ctx.cmd,ctx.cameraColorBuffer,ctx.cameraDepthBuffer,ClearFlag.None);
                Frame=Time.frameCount;armed=false;
            }
            catch(Exception e) {Error=e.ToString();}
        }
        void Draw(CommandBuffer cmd,DatasetMaskTarget target,int pass)
        {
            foreach(var r in target.renderers) if(r!=null&&r.enabled&&r.gameObject.activeInHierarchy) {
                var mesh=r.GetComponent<MeshFilter>().sharedMesh;
                for(int s=0;s<mesh.subMeshCount;s++) cmd.DrawRenderer(r,material,s,pass);
            }
        }
        protected override void Cleanup()
        {
            CoreUtils.Destroy(material);if(Visible!=null) foreach(var rt in Visible) rt?.Release();if(Amodal!=null) foreach(var rt in Amodal) rt?.Release();
            Visible=null;Amodal=null;
            ObserverVisible?.Release();ObserverVisible=null;observerTarget=null;
        }
    }
}
