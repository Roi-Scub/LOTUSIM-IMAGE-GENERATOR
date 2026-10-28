using System;
using UnityEngine;
namespace Lotusim.Dataset
{
    public sealed class DatasetMeshAnimation : MonoBehaviour
    {
        public DatasetMeshAnimationClip clip;
        public MeshFilter[] targets;
        [NonSerialized] public bool externalClock;
        public int Frame {get;private set;}
        public void Apply(float seconds)
        {
            if(clip==null||clip.frames==null||clip.frames.Length==0||clip.durationSeconds<=0||targets==null) throw new InvalidOperationException("Incomplete baked mesh animation.");
            Frame=Mathf.Min(clip.frames.Length-1,Mathf.FloorToInt(Mathf.Repeat(seconds,clip.durationSeconds)/clip.durationSeconds*clip.frames.Length));
            var parts=clip.frames[Frame].parts;
            if(parts==null||parts.Length!=targets.Length) throw new InvalidOperationException("Mesh animation material count mismatch.");
            for(int i=0;i<targets.Length;i++) targets[i].sharedMesh=parts[i];
        }
        void LateUpdate(){if(!externalClock)Apply(Time.time);}
    }
}
