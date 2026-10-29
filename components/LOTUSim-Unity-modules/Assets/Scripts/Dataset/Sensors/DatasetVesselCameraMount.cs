using System;
using UnityEngine;
using UnityEngine.Rendering;

namespace Lotusim.Dataset
{
    // Rigid mounting, deliberately not a gimbal: the horizon rolls with the hull.
    // Remains active for the preview after the recording has completed.
    [DisallowMultipleComponent, DefaultExecutionOrder(-4400)]
    public sealed class DatasetVesselCameraMount : MonoBehaviour
    {
        MarineVesselWaveMotion response;
        Camera view;
        Transform originalParent;
        Vector3 originalPosition;
        Quaternion originalRotation;
        bool attached;
        public void Attach(MarineVesselWaveMotion vessel, Camera camera, Vector3 offset, Quaternion localRotation)
        {
            if (attached)
                throw new InvalidOperationException("Camera is already mounted.");
            response = vessel;
            view = camera;
            originalParent = view.transform.parent;
            originalPosition = view.transform.localPosition;
            originalRotation = view.transform.localRotation;
            view.transform.SetParent(response.visual, false);
            view.transform.localPosition = offset;
            view.transform.localRotation = localRotation;
            attached = true;
        }

        void LateUpdate()
        {
            if (attached && response != null && response.isActiveAndEnabled && view != null)
                response.SampleForCamera(default(ScriptableRenderContext), view);
        }

        public void Detach()
        {
            if (!attached)
                return;
            attached = false;
            if (view != null)
            {
                view.transform.SetParent(originalParent, false);
                view.transform.localPosition = originalPosition;
                view.transform.localRotation = originalRotation;
            }
        }

        void OnDisable()
        {
            Detach();
        }
    }
}
