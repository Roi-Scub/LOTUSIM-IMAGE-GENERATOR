using System;
using System.IO;
using Lotusim.Dataset;
using UnityEditor;
using UnityEditor.AddressableAssets;
using UnityEditor.AddressableAssets.Settings;
using UnityEngine;

namespace Lotusim.EditorTools
{
    public static class DatasetFastDroneBuilder
    {
        public const string Model="drone_racer_sim",Path="Assets/Prefabs/drone_racer_sim.prefab",Marker="FastDroneBankVisual";
        public static void Ensure()
        {
            var existing=AssetDatabase.LoadAssetAtPath<GameObject>(Path);
            if(existing!=null&&existing.transform.Find(Marker)==null)throw new IOException("Refusing to replace an unowned drone_racer_sim prefab.");
            if(existing==null)CreatePrefab();
            // Also register an already generated prefab after deployment into
            // another checkout; registration is idempotent and uses one key.
            var settings=AddressableAssetSettingsDefaultObject.Settings;if(settings!=null){var group=settings.FindGroup("SpawnInterface")??settings.DefaultGroup;var entry=settings.CreateOrMoveEntry(AssetDatabase.AssetPathToGUID(Path),group);entry.address=Model;settings.SetDirty(AddressableAssetSettings.ModificationEvent.EntryModified,entry,true,true);EditorUtility.SetDirty(group);}
            AssetDatabase.SaveAssets();
        }
        static void CreatePrefab()
        {
            const string source="Assets/Prefabs/small_drone.prefab";if(AssetDatabase.LoadAssetAtPath<GameObject>(source)==null)throw new FileNotFoundException("Original procedural small_drone prefab required.");
            var root=PrefabUtility.LoadPrefabContents(source);
            try{
                root.name=Model;var bank=new GameObject(Marker).transform;bank.SetParent(root.transform,false);
                for(int i=root.transform.childCount-1;i>=0;i--){var child=root.transform.GetChild(i);if(child!=bank)child.SetParent(bank,false);}
                var response=root.GetComponent<DatasetAerialResponse>()??root.AddComponent<DatasetAerialResponse>();response.visual=bank;response.maxBankDeg=1;response.maxPitchDeg=.8f;
                if(PrefabUtility.SaveAsPrefabAsset(root,Path)==null)throw new IOException("Cannot save high-speed visual drone alias");
            }finally{PrefabUtility.UnloadPrefabContents(root);}
            Debug.Log("[Fast Drone] Unarmed procedural appearance alias ready. Synthetic speed profile only; ordinary quadcopter limits unchanged.");
        }
    }
}
