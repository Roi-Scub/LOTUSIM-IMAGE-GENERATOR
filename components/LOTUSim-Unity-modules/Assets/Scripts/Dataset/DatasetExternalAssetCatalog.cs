using System;
namespace Lotusim.Dataset
{
    // Appearance aliases only: existing class IDs and trajectories are unchanged.
    public static class DatasetExternalAssetCatalog
    {
        public static readonly string[] Models={"buoy_navigation_ozzy","drone_amvlab","helicopter_utility_gb","airplane_a320","airplane_c172","seagull_dayvable","speedboat_smolbot","speedboat_racing"};
        public static readonly string[] Categories={"buoy","drone","helicopter","airplane","airplane","bird","speedboat","speedboat"};
        public static readonly string[] Names={"Balise de navigation","Drone AMV","Hélicoptère de transport","Airbus A320","Cessna 172","Goéland animé","Hors-bord ouvert","Hors-bord de course"};
        public static bool Matches(string model,string category)
        {
            if(model=="drone_racer_sim")return category=="drone";
            int index=Array.IndexOf(Models,model);
            if(index>=0) return Categories[index]==category;
            index=Array.IndexOf(DatasetBoatVariants.Models,model);
            return index>=0&&DatasetBoatVariants.Categories[index]==category||DatasetImportedAssetRegistry.Matches(model,category);
        }
    }
}
