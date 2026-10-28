using System;
using UnityEngine;
namespace Lotusim.Dataset
{
    // Visual perturbation, NOT validated aerodynamic dynamics. Never writes the
    // root: LOTUSim remains the sole trajectory owner in connected captures.
    public sealed class DatasetAerialResponse : MonoBehaviour
    {
        public Transform visual;
        public float maxBankDeg=3,maxPitchDeg=1.2f;
        [NonSerialized] public bool externalClock;
        public void Apply(float seconds,float phase=0,float coordinatedBankDeg=0)
        {
            if(visual==null)return;
            visual.localRotation=Quaternion.Euler(coordinatedBankDeg+maxBankDeg*Mathf.Sin(seconds*.73f+phase),0,maxPitchDeg*Mathf.Sin(seconds*.51f+phase));
        }
        void LateUpdate(){if(!externalClock)Apply(Time.time);}
    }
}
