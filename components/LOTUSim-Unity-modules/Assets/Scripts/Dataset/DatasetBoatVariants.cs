using System;
using System.IO;
using System.Linq;
using UnityEngine;

namespace Lotusim.Dataset
{
    public static class DatasetBoatVariants
    {
        public static readonly string[] Models={"speedboat_zefiro","rib_assault","motor_yacht_35","jetski_seadoo_gti","cabin_cruiser_minnow","rib_zodiac"};
        public static readonly string[] Categories={"speedboat","speedboat","motor_yacht","jetski","motor_yacht","speedboat"};
        public static readonly string[] DisplayNames={"Zefiro — hors-bord","Semi-rigide d’intervention","Yacht 35 pieds","Jet-ski Sea-Doo GTI","Bateau à cabine Minnow","Semi-rigide bimoteur"};
        public static GameObject Resolve(DatasetEncounterClass definition,DatasetEncounter encounter)
        {
            if(string.IsNullOrEmpty(encounter.modelName)||definition.prefab!=null&&encounter.modelName==definition.prefab.name) return definition.prefab;
            var result=definition.prefabVariants?.SingleOrDefault(p=>p!=null&&p.name==encounter.modelName);
            if(result==null) throw new InvalidOperationException("Planned prefab variant is missing: "+encounter.modelName);
            return result;
        }
        public static string Select(DatasetEncounterClass definition,int seed,int trackId)
        {
            int length=definition.prefabVariants?.Length??0;
            if(length==0) return definition.prefab==null?"":definition.prefab.name;
            // Separate PRNG: adding appearances never changes any trajectory,
            // weather draw, class ID, instance name or tracking identity.
            int choice=new System.Random(unchecked(seed*397^trackId*7919)).Next(length+1);
            var prefab=choice==0?definition.prefab:definition.prefabVariants[choice-1];
            return prefab==null?"":prefab.name;
        }
        [Serializable] sealed class CreditManifest
        {
            public string policy="Per-asset licenses and declared provenance retained; modifications listed; trademarks/publicity not licensed; no creator endorsement or legal verification implied";
            public OpenBoatCredit[] assets;
        }
        public static void WriteCredits(string directory,DatasetSequenceActor[] actors)
        {
            var values=actors.Select(a=>a.root.GetComponent<OpenBoatAssetCredit>()).Where(c=>c!=null).Select(c=>c.credit).GroupBy(c=>c.model).Select(g=>g.First()).ToArray();
            if(values.Length>0) DatasetSequenceExport.Atomic(Path.Combine(directory,"asset-attributions.json"),JsonUtility.ToJson(new CreditManifest{assets=values},true));
        }
    }
}
