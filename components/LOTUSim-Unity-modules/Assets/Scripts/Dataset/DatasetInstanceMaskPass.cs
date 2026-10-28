using System;
using UnityEngine;
using UnityEngine.Experimental.Rendering;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace Lotusim.Dataset
{
    [Serializable]
    public sealed class DatasetInstanceMaskPass : CustomPass
    {
        [NonSerialized] public Camera captureCamera;
        [NonSerialized] public MeshRenderer[] targetRenderers;
        [NonSerialized] public int width,height;
        [NonSerialized] public bool armed;
        public int Frame {get;private set;}=-1;
        public RTHandle Visible {get;private set;}
        public RTHandle Amodal {get;private set;}
        public string Error {get;private set;}
        Material m_material;
        protected override bool executeInSceneView=>false;

        protected override void Setup(ScriptableRenderContext context,CommandBuffer cmd)
        {
            var shader=Resources.Load<Shader>("Dataset/InstanceMask");
            if(shader==null||!shader.isSupported) {Error="Dataset mask shader is unavailable or unsupported.";return;}
            m_material=CoreUtils.CreateEngineMaterial(shader);
            // Scaled handles share the backing dimensions of HDRP's camera
            // depth, including when the editor's Scene view is larger.
            Visible=RTHandles.Alloc(Vector2.one,colorFormat:GraphicsFormat.R8G8B8A8_UNorm,useDynamicScale:false,name:"Dataset visible instance mask");
            Amodal=RTHandles.Alloc(Vector2.one,colorFormat:GraphicsFormat.R8G8B8A8_UNorm,useDynamicScale:false,name:"Dataset amodal instance mask");
        }
        protected override void Execute(CustomPassContext ctx)
        {
            if(!armed||ctx.hdCamera.camera!=captureCamera||Error!=null) return;
            try {
                if(ctx.hdCamera.actualWidth!=width||ctx.hdCamera.actualHeight!=height)
                    throw new InvalidOperationException("Mask/RGB camera dimensions differ; dynamic resolution is unsupported.");
                // HDRP 14's water GBuffer updates this depth before
                // BeforeTransparent. Water is an opaque occluder for labels,
                // even if RGB refraction still reveals a submerged fragment.
                CoreUtils.SetRenderTarget(ctx.cmd,Visible,ctx.cameraDepthBuffer,ClearFlag.Color,Color.black);
                Draw(ctx.cmd,0);
                CoreUtils.SetRenderTarget(ctx.cmd,Amodal,ClearFlag.Color,Color.black);
                Draw(ctx.cmd,1);
                CoreUtils.SetRenderTarget(ctx.cmd,ctx.cameraColorBuffer,ctx.cameraDepthBuffer,ClearFlag.None);
                Frame=Time.frameCount;armed=false;
            }
            catch(Exception e) {Error=e.ToString();}
        }
        void Draw(CommandBuffer cmd,int pass)
        {
            foreach(var renderer in targetRenderers) {
                if(renderer==null||!renderer.enabled||!renderer.gameObject.activeInHierarchy) continue;
                var mesh=renderer.GetComponent<MeshFilter>().sharedMesh;
                for(int sub=0;sub<mesh.subMeshCount;sub++) cmd.DrawRenderer(renderer,m_material,sub,pass);
            }
        }
        protected override void Cleanup()
        {
            CoreUtils.Destroy(m_material);m_material=null;
            Visible?.Release();Visible=null;Amodal?.Release();Amodal=null;
        }
    }
}
