using Lotusim.Dataset;
using UnityEditor;
using UnityEngine;

namespace Lotusim.EditorTools
{
    public static partial class DatasetLotusimSceneBuilder
    {
        public static void ConfigureSensors(DatasetSequenceConfig config)
        {
            if (config.width == 1920 && config.height == 1080)
            {
                config.width = 3840;
                config.height = 2160;
            }

            config.sensors = new DatasetSensorSettings
            {
                thermal = true,
                nightVision = true
            };
            config.connectedSensorsVersion = 1;
            config.Validate();
            EditorUtility.SetDirty(config);
            Debug.Log("[LOTUSim Sensors] Native 4K (for former Full HD config), RGB + synthetic IR + night vision enabled. Timing, route, sea and encounter settings preserved.");
        }
    }
}
