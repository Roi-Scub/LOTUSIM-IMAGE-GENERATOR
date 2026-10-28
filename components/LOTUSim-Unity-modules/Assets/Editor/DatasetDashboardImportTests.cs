using System;
using System.IO;
using System.Linq;
using Lotusim.Dataset;
using UnityEditor;
using UnityEngine;

namespace Lotusim.EditorTools
{
    public static class DatasetDashboardImportTests
    {
        static int checks;
        [MenuItem("LOTUSim/Models/Dashboard imports/Validate contracts without importing")]
        public static void ValidateWithoutImport()
        {
            checks=0;
            var request=ValidRequest();
            DatasetDashboardImportContract.Validate(request,request.id);Check(true,"valid minimal request");
            Check(DatasetDashboardImportContract.ImportId(request.model)==request.id,"canonical identity");
            Check(!DatasetImportedAssetRegistry.ModelKey("import_bad"),"no blind prefix trust");
            Check(!DatasetImportedAssetRegistry.ModelKey("import_"+new string('g',32)),"hex key only");
            Check(DatasetImportedAssetRegistry.ClassId("other")==13&&DatasetImportedAssetRegistry.ClassId("buoy")==1&&DatasetImportedAssetRegistry.ClassId("sailboat")==12,"stable categories");
            foreach(var path in new[]{"../secret","/absolute","a/../b","a\\b",".hidden","a//b","a:evil","textures/../x.png"})
                Reject(()=>DatasetDashboardImportContract.RelativePath(path),"path refused");
            foreach(var path in new[]{"geometry.bytes","model-info.json","textures/base color.png"}) {DatasetDashboardImportContract.RelativePath(path);Check(true,"safe relative path");}
            var wrong=ValidRequest();wrong.id="import-00000000-0000-0000-0000-000000000000";Reject(()=>DatasetDashboardImportContract.Validate(wrong,wrong.id),"mismatched UUID");
            wrong=ValidRequest();wrong.classId=1;Reject(()=>DatasetDashboardImportContract.Validate(wrong,wrong.id),"mismatched class");
            wrong=ValidRequest();wrong.domain="air";Reject(()=>DatasetDashboardImportContract.Validate(wrong,wrong.id),"domain mismatch");
            wrong=ValidRequest();wrong.profile.maxSpeedMps=1;Reject(()=>DatasetDashboardImportContract.Validate(wrong,wrong.id),"static object motion refused");
            wrong=ValidRequest();wrong.dimensions.heightM=float.NaN;Reject(()=>DatasetDashboardImportContract.Validate(wrong,wrong.id),"nonfinite dimensions");
            wrong=ValidRequest();wrong.bundleDirectory="prepared/../escape";Reject(()=>DatasetDashboardImportContract.Validate(wrong,wrong.id),"bundle path mismatch");
            wrong=ValidRequest();wrong.files[0].path="attack.cs";Reject(()=>DatasetDashboardImportContract.Validate(wrong,wrong.id),"source scripts forbidden");
            wrong=ValidRequest();wrong.files[0].bytes=DatasetDashboardImportContract.MaximumFileBytes+1;Reject(()=>DatasetDashboardImportContract.Validate(wrong,wrong.id),"allocation limit");
            wrong=ValidRequest();wrong.files=new[]{wrong.files[0],wrong.files[0]};Reject(()=>DatasetDashboardImportContract.Validate(wrong,wrong.id),"duplicate inventory");
            Check(!DatasetDashboardImportContract.Range(float.PositiveInfinity,0,100),"infinite bound refused");
            Check(DatasetDashboardImportContract.Hash(new byte[]{1,2,3}).Length==64,"SHA256 output");
            var bundle=ScriptableObject.CreateInstance<DatasetManualPlanBundle>();
            try {
                bundle.planJson="plan";bundle.campaignJson="campaign";
                Check(bundle.ComputeHash()==DatasetTrafficPlanBundle.Hash("plan|campaign"),"legacy bundle digest unchanged");
                bundle.importedAssetRevisions=new[]{new DatasetImportedAssetRevision{model=request.model,requestSha256=new string('a',64),revisionSha256=new string('b',64)}};
                Check(bundle.ComputeHash()!=DatasetTrafficPlanBundle.Hash("plan|campaign"),"imported revisions protected by bundle digest");
            }finally {UnityEngine.Object.DestroyImmediate(bundle);}
            Debug.Log("[Dashboard Import] PASS "+checks+" contract checks; no asset import, scene change, Play or ROS request.");
        }
        static DashboardMeshRequest ValidRequest()=>new DashboardMeshRequest{
            schema="lotusim-unity-mesh-import-1",id="import-12345678-1234-4234-8234-123456789abc",model="import_12345678123442348234123456789abc",
            revisionSha256=new string('a',64),category="other",classId=13,domain="moored",label="Contract fixture",license="Original QA geometry",
            bundleDirectory="prepared/"+new string('a',64),geometryFile="geometry.bytes",infoFile="model-info.json",
            dimensions=new DashboardMeshDimensions{lengthM=1,beamM=1,heightM=1,draftM=0},profile=new DashboardMeshProfile{bufferM=1},
            files=new[]{new DashboardMeshFile{path="geometry.bytes",sha256=new string('b',64),bytes=10},new DashboardMeshFile{path="model-info.json",sha256=new string('c',64),bytes=10},
                new DashboardMeshFile{path="gazebo.obj",sha256=new string('d',64),bytes=10},new DashboardMeshFile{path="gazebo.mtl",sha256=new string('e',64),bytes=10}}};
        static void Check(bool condition,string message){if(!condition)throw new InvalidDataException(message);checks++;}
        static void Reject(Action action,string message){try{action();}catch(ArgumentException){checks++;return;}catch(InvalidDataException){checks++;return;}throw new InvalidDataException("Expected rejection: "+message);}
    }
}
