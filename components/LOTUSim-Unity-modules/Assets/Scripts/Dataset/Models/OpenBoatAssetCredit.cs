using System;
using UnityEngine;

namespace Lotusim.Dataset
{
    [Serializable]
    public sealed class OpenBoatCredit
    {
        public string model, title, author, source, license, licenseUrl, sha256;
        public string[] changes;
    }

    // Credit travels with the prefab and is copied into every dataset using it.
    // No external model script, camera or animation is executed/imported.
    [DisallowMultipleComponent]
    public sealed class OpenBoatAssetCredit : MonoBehaviour
    {
        public OpenBoatCredit credit = new OpenBoatCredit();
    }
}
