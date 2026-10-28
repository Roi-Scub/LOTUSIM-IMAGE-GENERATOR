using System.Collections;
using UnityEngine;
using UnityEngine.Rendering.HighDefinition;

namespace Lotusim.Dataset
{
    // Normal ROS/Addressables scene support. Dataset runners configure these
    // themselves before activation, so this never creates a second controller.
    public sealed class DatasetBuoyAutoSetup : MonoBehaviour
    {
        IEnumerator Start()
        {
            if (GetComponent<BuoyWaveMotion>() != null)
                yield break;
            WaterSurface ocean = null;
            Camera camera = null;
            while (isActiveAndEnabled && (ocean == null || camera == null))
            {
                ocean = FindObjectOfType<WaterSurface>();
                camera = Camera.main ?? FindObjectOfType<Camera>();
                if (ocean == null || camera == null)
                    yield return null;
            }

            if (ocean == null || camera == null || GetComponent<BuoyWaveMotion>() != null)
                yield break;
            var visual = transform.Find(BuoyWaveMotion.VisualChildName);
            ocean.cpuSimulation = true;
            ocean.cpuFullResolution = true;
            gameObject.AddComponent<BuoyWaveMotion>().Configure(ocean, visual, camera, new DatasetFlotationSettings());
            gameObject.AddComponent<BuoyLanternFlash>().Configure(visual, camera, new DatasetLanternSettings());
        }
    }
}
