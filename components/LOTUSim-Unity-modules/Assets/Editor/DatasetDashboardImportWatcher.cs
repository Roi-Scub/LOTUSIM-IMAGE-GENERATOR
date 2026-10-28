using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Lotusim.Dataset;
using UnityEditor;
using UnityEditor.AddressableAssets;
using UnityEngine;

namespace Lotusim.EditorTools
{
    // Consumes only prepared, content-addressed local bundles. Inactive during
    // Play, compilation and AssetDatabase refresh; never starts Unity or ROS.
    [InitializeOnLoad]
    public static class DatasetDashboardImportWatcher
    {
        static double nextPoll;
        static bool processing;
        static readonly HashSet<string> unwritableResults=new HashSet<string>(StringComparer.Ordinal);
        public static string ImportRoot=>Path.GetFullPath(Path.Combine(Application.dataPath,"..","..","LOTUSim","artifacts","mesh-library","imports"));
        static DatasetDashboardImportWatcher(){EditorApplication.update+=Tick;}
        static void Tick()
        {
            if(Application.isBatchMode||processing||EditorApplication.isPlayingOrWillChangePlaymode||EditorApplication.isCompiling||EditorApplication.isUpdating||EditorApplication.timeSinceStartup<nextPoll)return;
            nextPoll=EditorApplication.timeSinceStartup+3;
            ProcessPending(false);
        }
        [MenuItem("LOTUSim/Models/Dashboard imports/Process pending imports now")]
        public static void ProcessPendingNow()=>ProcessPending(true);
        public static void ProcessPending(bool retryFailed)
        {
            if(processing||EditorApplication.isPlayingOrWillChangePlaymode||EditorApplication.isCompiling||EditorApplication.isUpdating)return;
            if(!Directory.Exists(ImportRoot))return;
            processing=true;
            try {
                DatasetDashboardImportContract.NoLinks(ImportRoot);
                foreach(string directory in Directory.GetDirectories(ImportRoot).OrderBy(p=>p,StringComparer.Ordinal).Take(2000)) {
                    string id=Path.GetFileName(directory);
                    if(!id.StartsWith("import-",StringComparison.Ordinal)||!Guid.TryParseExact(id.Substring(7),"D",out var parsed)||id!="import-"+parsed.ToString("D"))continue;
                    DatasetDashboardImportContract.NoLinks(directory);
                    string requestPath=Path.Combine(directory,"unity-request.json");if(!File.Exists(requestPath))continue;
                    byte[] raw;string requestSha;DashboardMeshRequest request=null;
                    try {raw=DatasetDashboardImportContract.ReadRequest(requestPath);requestSha=DatasetDashboardImportContract.Hash(raw);}
                    catch(Exception){continue;}
                    string key=id+":"+requestSha;
                    if(!retryFailed&&unwritableResults.Contains(key))continue;
                    string resultPath=Path.Combine(directory,"unity-result.json");
                    var prior=ReadResult(resultPath);
                    if(prior?.id==id&&prior.requestSha256==requestSha&&(prior.status=="failed"&&!retryFailed||prior.status=="ready"&&ReadyStillExists(prior)))continue;
                    try {
                        request=JsonUtility.FromJson<DashboardMeshRequest>(new UTF8Encoding(false,true).GetString(raw));
                        DatasetDashboardImportContract.Validate(request,id);
                        var result=DatasetDashboardMeshBuilder.Build(request,directory,requestSha);
                        // A source revision may have changed during a long import.
                        // Never acknowledge this result as the current request.
                        if(DatasetDashboardImportContract.Hash(DatasetDashboardImportContract.ReadRequest(requestPath))!=requestSha)continue;
                        DatasetDashboardImportContract.AtomicResult(resultPath,result);
                        unwritableResults.Remove(key);
                        Debug.Log("[Dashboard Import] Ready: "+request.model+" ("+request.category+"). No scenario launched.");
                    }catch(Exception error) {
                        var result=new DashboardMeshResult{status="failed",id=id,model=request?.model??"",requestSha256=requestSha,
                            revisionSha256=request?.revisionSha256??"",unityProjectPath=Path.GetFullPath(Path.Combine(Application.dataPath,"..")),
                            error="Unity could not integrate this prepared model: "+error.GetType().Name+". "+SafeError(error.Message),updatedAt=DateTime.UtcNow.ToString("o")};
                        try {DatasetDashboardImportContract.AtomicResult(resultPath,result);}
                        catch(Exception){unwritableResults.Add(key);/* No repeat geometry import loop if the receipt itself is unwritable. */}
                        Debug.LogWarning("[Dashboard Import] Import not ready: "+id+". See its dashboard status.");
                    }
                    break; // At most one new model per editor tick.
                }
            }catch(Exception error) {Debug.LogWarning("[Dashboard Import] Local queue unavailable: "+error.GetType().Name);}
            finally {processing=false;}
        }
        static string SafeError(string value)
        {
            string message=(value??"").Replace(ImportRoot,"<import-library>").Replace(Application.dataPath,"<Unity-Assets>");
            return message.Length>350?message.Substring(0,350):message;
        }
        static DashboardMeshResult ReadResult(string path)
        {
            try {if(!File.Exists(path))return null;var value=JsonUtility.FromJson<DashboardMeshResult>(new UTF8Encoding(false,true).GetString(DatasetDashboardImportContract.ReadRequest(path)));return value?.schema=="lotusim-unity-mesh-result-1"?value:null;}
            catch(Exception){return null;}
        }
        static bool ReadyStillExists(DashboardMeshResult result)
        {
            try {
                if(!DatasetImportedAssetRegistry.ModelKey(result.model)||DatasetDashboardImportContract.ImportId(result.model)!=result.id||
                    result.prefabPath!=DatasetDashboardMeshBuilder.PrefabPath(result.model)||result.addressableKey!=result.model||!DatasetImportedAssetRegistry.Hex(result.prefabSha256,64)||
                    !DatasetImportedAssetRegistry.Hex(result.prefabGuid,32)||!DatasetImportedAssetRegistry.Hex(result.revisionSha256,64))return false;
                string project=Path.GetFullPath(Path.Combine(Application.dataPath,".."));if(result.unityProjectPath!=project)return false;
                var asset=AssetDatabase.LoadAssetAtPath<GameObject>(result.prefabPath)?.GetComponent<DatasetImportedAsset>();
                return asset!=null&&asset.importId==result.id&&asset.model==result.model&&asset.requestSha256==result.requestSha256&&
                    asset.revisionSha256==result.revisionSha256&&AssetDatabase.AssetPathToGUID(result.prefabPath)==result.prefabGuid&&
                    DatasetDashboardImportContract.FileHash(result.prefabPath)==result.prefabSha256&&
                    AddressableAssetSettingsDefaultObject.Settings?.FindAssetEntry(result.prefabGuid)?.address==result.model&&
                    DatasetImportedAssetRegistry.Matches(result.model,asset.category);
            }catch(Exception){return false;}
        }
    }
}
