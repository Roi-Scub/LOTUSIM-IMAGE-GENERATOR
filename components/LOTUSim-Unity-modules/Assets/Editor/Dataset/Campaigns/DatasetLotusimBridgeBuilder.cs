using Lotusim.Dataset;
using UnityEditor;
using UnityEngine;

namespace Lotusim.EditorTools
{
    public static partial class DatasetLotusimSceneBuilder
    {
        public static void ConfigureBridge(DatasetSequenceConfig config)
        {
            // Front of the sloped opaque bridge glazing: mesh raycasts give
            // x~29 m at y=12 m. Keep the eye in front, not inside the solid shell.
            config.observerDeckCamera = true;
            config.observerDeckOffsetM = new Vector3(30.3f, 12.4f, -5.5f);
            config.observerHeightM = 12.4f;
            config.observerCameraStation = "navigation_bridge_front";
            config.observerWaveTiltGain = 1.8f;
            config.observerMaxRollDeg = 7;
            config.observerMaxPitchDeg = 4;
            config.connectedBridgeVersion = 1;
            config.Validate();
            config.MakePlan();
            EditorUtility.SetDirty(config);
            Debug.Log("[LOTUSim Camera] Rigid non-stabilized navigation bridge mount enabled. Entire FREMM wave tilt amplified, not a separate camera wobble. Preview stays mounted after recording.");
        }
    }
}
