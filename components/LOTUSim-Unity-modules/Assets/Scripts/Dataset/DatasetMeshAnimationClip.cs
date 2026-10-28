using System;
using UnityEngine;
namespace Lotusim.Dataset
{
    [Serializable] public sealed class DatasetMeshFrame {public Mesh[] parts;}
    public sealed class DatasetMeshAnimationClip : ScriptableObject
    {
        public string provenance;
        public float durationSeconds=1;
        public DatasetMeshFrame[] frames;
    }
}
