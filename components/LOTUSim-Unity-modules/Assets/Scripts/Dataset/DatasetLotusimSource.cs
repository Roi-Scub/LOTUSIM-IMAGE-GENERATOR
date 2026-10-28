using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Unity.Robotics.ROSTCPConnector;
using Unity.Robotics.ROSTCPConnector.MessageGeneration;
using UnityEngine;

namespace Lotusim.Dataset
{
    public static class DatasetLotusimProtocol
    {
        [Serializable] sealed class Capabilities {public string schema,snapshotSchema;public bool ownedStop,steppedTimeline,constantTurnTrajectories,boundedTurnTrajectories;public float maxDatasetSpeedMps;}
        public const string ReloadHelp="Quit Play, stop Gazebo, rebuild lotusim_mas in /workspace, then restart maritime_dataset.world. Keep the ROS TCP endpoint running.";
        static T Parse<T>(string json,string stage) where T:class
        {
            string text=json==null?"":json.Trim();
            try {
                if(!text.StartsWith("{",StringComparison.Ordinal)) throw new ArgumentException("Expected a JSON object");
                var value=JsonUtility.FromJson<T>(text);
                if(value==null) throw new ArgumentException("Empty JSON object");
                return value;
            } catch(ArgumentException e) {
                string excerpt=text.Length<=240?text:text.Substring(0,240)+"…";
                throw new InvalidOperationException("Incompatible LOTUSim response during "+stage+": '"+excerpt+"'. "+ReloadHelp+" No generic scenario stop was sent.",e);
            }
        }
        public static void CheckCapabilities(string json,bool requireTurn=false,float requiredSpeedMps=0,bool requireBoundedTurn=false)
        {
            var c=Parse<Capabilities>(json,"protocol preflight");
            if(c.schema!="lotusim-dataset-capabilities-1"||c.snapshotSchema!="lotusim-dataset-step-1"||!c.ownedStop||!c.steppedTimeline)
                throw new InvalidOperationException("The running LOTUSim module does not support this dataset protocol. "+ReloadHelp);
            if(requireTurn&&!c.constantTurnTrajectories) throw new InvalidOperationException("The running LOTUSim module has no constant-turn trajectories. "+ReloadHelp+" No scenario was launched.");
            if(requireBoundedTurn&&!c.boundedTurnTrajectories)throw new InvalidOperationException("The running LOTUSim module needs the bounded drone-turn update. "+ReloadHelp+" No scenario was launched.");
            if(requiredSpeedMps>(c.maxDatasetSpeedMps>0?c.maxDatasetSpeedMps:200))throw new InvalidOperationException("LOTUSim must be rebuilt/restarted to support airliner cruise speeds above 200 m/s. "+ReloadHelp+" No scenario was launched.");
        }
        public static DatasetLotusimFrame ReadFrame(string json,string stage)
        {
            var frame=Parse<DatasetLotusimFrame>(json,stage);
            if(frame.schema!="lotusim-dataset-step-1") throw new InvalidOperationException("Unsupported LOTUSim snapshot schema. "+ReloadHelp);
            return frame;
        }
    }
    [Serializable] public sealed class DatasetLotusimObject
    {
        public string instance,model;
        public ulong entity;
        public Vector3 position,velocity; // ENU, from the Gazebo ECM.
        public Quaternion rotation;
        public Pose UnityPose=>CoordinateSystemUtils.GzPoseToUnityPose(new Pose(position,rotation));
        public Vector3 UnityVelocity=>new Vector3(velocity.x,velocity.z,velocity.y);
    }
    [Serializable] public sealed class DatasetLotusimFrame
    {
        public string schema,scenario,runId,planId,observer,motionSource;
        public int frame,fps,frames;
        public double timeSeconds,worldTimeSeconds;
        public DatasetLotusimObject[] objects;
        public void Validate(string token,string plan,int expectedFrame,int expectedFps,int expectedFrames,string expectedScenario=DatasetLotusimScenario.Name)
        {
            if(schema!="lotusim-dataset-step-1"||scenario!=expectedScenario||runId!=token||planId!=plan||
                observer!=DatasetLotusimScenario.Observer||frame!=expectedFrame||fps!=expectedFps||frames!=expectedFrames||
                Math.Abs(timeSeconds-frame/(double)fps)>1e-5||double.IsNaN(timeSeconds)||double.IsNaN(worldTimeSeconds)||
                double.IsInfinity(timeSeconds)||double.IsInfinity(worldTimeSeconds)||objects==null||objects.Length<1||objects.Length>41||
                objects.Any(o=>o==null||string.IsNullOrEmpty(o.instance)||string.IsNullOrEmpty(o.model)||o.entity==0||
                    !Finite(o.position)||!Finite(o.velocity)||!Finite(new Vector3(o.rotation.x,o.rotation.y,o.rotation.z))||
                    float.IsNaN(o.rotation.w)||float.IsInfinity(o.rotation.w)||Math.Abs(Quaternion.Dot(o.rotation,o.rotation)-1)>.01f)||
                objects.Select(o=>o.instance).Distinct().Count()!=objects.Length||objects.Count(o=>o.instance==observer)!=1)
                throw new InvalidOperationException("Invalid, stale or mismatched LOTUSim snapshot; no image was saved.");
        }
        static bool Finite(Vector3 v)=>!(float.IsNaN(v.x)||float.IsNaN(v.y)||float.IsNaN(v.z)||float.IsInfinity(v.x)||float.IsInfinity(v.y)||float.IsInfinity(v.z));
    }

    // One existing ROSConnection, no second socket and no legacy RosInterface.
    // Services carry authoritative ECM snapshots and acknowledge every frame.
    [DefaultExecutionOrder(-4600)]
    public sealed class DatasetLotusimSource : MonoBehaviour
    {
        public string rosAddress="127.0.0.1",rosNamespace="lotusim",scenarioFile="MaritimeRandomLotusim.yaml";
        public int rosPort=10000;
        public float timeoutSeconds=60;
        public GameObject observerPrefab;
        [HideInInspector] public int observerSetupVersion;
        public string Status {get;private set;}="idle";
        public string Error {get;private set;}
        public bool HasFrame {get;private set;}
        public DatasetLotusimFrame Current {get;private set;}
        public string CurrentJson {get;private set;}
        public string LastResponse {get;private set;}
        public string RunId {get;private set;}
        public bool CleanupFinished {get;private set;}
        public bool CleanupConfirmed {get;private set;}
        public int ConnectionInstanceId=>ros==null?0:ros.GetInstanceID();
        ROSConnection ros;
        Task<DatasetStringResponse> pending;
        string planId,launchService,controlService,expectedScenario;
        float requiredSpeedMps;
        int fps,frames,requestedFrame;
        float since;
        bool begun,stopSent,requireTurn,requireBoundedTurn;
        public void Begin(DatasetSequenceConfig config,DatasetSequencePlan plan)
        {
#if !ROS2
            throw new InvalidOperationException("Enable ROS2 in Robotics > ROS Settings before starting the LOTUSim dataset.");
#endif
            if(begun) throw new InvalidOperationException("LOTUSim source already started.");
            if(observerSetupVersion<2) throw new InvalidOperationException("Update the connected scene with LOTUSim > Dataset > 7 before Play to configure the FREMM observer and regenerate its scenario.");
            if(config.connectedLightingVersion<1) throw new InvalidOperationException("Apply day/evening/night lighting and regenerate the scenario with LOTUSim > Dataset > 7 before Play.");
            if(string.IsNullOrWhiteSpace(rosAddress)||rosPort<1||rosPort>65535||timeoutSeconds<1||timeoutSeconds>300||observerPrefab==null||
                string.IsNullOrWhiteSpace(rosNamespace)||scenarioFile!=System.IO.Path.GetFileName(scenarioFile)||!scenarioFile.EndsWith(".yaml",StringComparison.Ordinal))
                throw new ArgumentException("Invalid LOTUSim connection/scenario settings.");
            if(FindObjectsOfType<LotusimInterface>(true).Length>0||FindObjectsOfType<DatasetLotusimSource>(true).Length!=1)
                throw new InvalidOperationException("Use the dedicated connected dataset scene alone; a second pose consumer/writer is present.");
            if(FindObjectsOfType<ROSConnection>(true).Length>1) throw new InvalidOperationException("More than one ROSConnection exists; no additional connection was opened.");
            planId=DatasetLotusimScenario.PlanId(config,plan);fps=config.simulationFps;frames=config.SimulationFrames;
            expectedScenario=config.ScenarioName;requiredSpeedMps=plan.events.Max(e=>e.velocity.magnitude);
            requireTurn=Mathf.Abs(config.observerTurnDeg)>.0001f||plan.events.Any(e=>Mathf.Abs(e.yawRateDegS)>.0001f);requireBoundedTurn=plan.events.Any(e=>e.boundedTurn);
            ros=ROSConnection.GetOrCreateInstance();
            if(ros.HasConnectionThread&&(ros.RosIPAddress!=rosAddress||ros.RosPort!=rosPort)) throw new InvalidOperationException("An existing ROS connection uses another address/port.");
            ros.ConnectOnStart=false;ros.RosIPAddress=rosAddress;ros.RosPort=rosPort;ros.listenForTFMessages=false;ros.ShowHud=false;
            MessageRegistry.Register(DatasetStringRequest.RosName,DatasetStringRequest.Deserialize);
            MessageRegistry.Register(DatasetStringRequest.RosName,DatasetStringResponse.Deserialize,MessageSubtopic.Response);
            string prefix="/"+rosNamespace.Trim('/');launchService=prefix+"/launch_scenario";controlService=prefix+"/dataset_control";
            if(!ros.HasConnectionThread) ros.Connect();
            begun=true;Status="connecting";since=Time.realtimeSinceStartup;
            Debug.Log("[LOTUSim Dataset] One ROS TCP connection: "+ConnectionInstanceId+" at "+rosAddress+":"+rosPort+". Namespace="+rosNamespace);
        }
        void Update()
        {
            if(!begun||Error!=null||CleanupFinished) return;
            try {
                if(Status=="connecting"&&!ros.HasConnectionError&&ros.HasConnectionThread&&ros.LastMessageReceivedRealtime>0) {
                    // Register after the handshake. Registering before Connect
                    // queues a command AND registers again on connection start.
                    if(ros.GetTopic(launchService)?.IsRosService!=true) ros.RegisterRosService<DatasetStringRequest,DatasetStringResponse>(launchService);
                    if(ros.GetTopic(controlService)?.IsRosService!=true) ros.RegisterRosService<DatasetStringRequest,DatasetStringResponse>(controlService);
                    Status="checking_protocol";Send(controlService,"{\"operation\":\"capabilities\"}");return;
                }
                if(pending!=null&&pending.IsCompleted) {
                    var task=pending;pending=null;
                    if(task.IsFaulted) throw task.Exception;
                    var response=task.Result;
                    LastResponse=response.message;
                    if(Status=="stopping") {CleanupFinished=true;CleanupConfirmed=response.success;Status=response.success?"stopped":"cleanup_unconfirmed";return;}
                    if(!response.success) throw new InvalidOperationException(Status=="checking_protocol"?
                        "LOTUSim rejected protocol preflight: "+response.message+". No scenario was launched. "+DatasetLotusimProtocol.ReloadHelp:
                        "LOTUSim refused the request: "+response.message+". No existing scenario was stopped.");
                    if(Status=="checking_protocol") {
                        DatasetLotusimProtocol.CheckCapabilities(response.message,requireTurn,requiredSpeedMps,requireBoundedTurn);
                        Debug.Log("[LOTUSim Dataset] Compatible stepped/owned protocol confirmed; launching scenario.");
                        Status="launching";Send(launchService,scenarioFile);return;
                    }
                    var frame=DatasetLotusimProtocol.ReadFrame(response.message,Status);
                    if(Status=="launching") {
                        // Retain the token even if the authoring config is mismatched, so
                        // cleanup can target only the scenario we just launched.
                        RunId=frame.runId;
                        if(string.IsNullOrEmpty(RunId)||frame.planId!=planId||frame.fps!=fps||frame.frames!=frames||frame.scenario!=expectedScenario)
                            throw new InvalidOperationException("LOTUSim YAML differs from the Unity configuration. Regenerate it with Dataset menu 8 before Play.");
                        Debug.Log("[LOTUSim Dataset] Owned scenario launched. Source: LOTUSim ECM; waiting for frame 0.");
                        RequestFrame(0);return;
                    }
                    frame.Validate(RunId,planId,requestedFrame,fps,frames,expectedScenario);Current=frame;CurrentJson=response.message;HasFrame=true;Status="ready";
                }
                if((pending!=null||Status=="connecting")&&Time.realtimeSinceStartup-since>timeoutSeconds)
                    throw new TimeoutException(Status=="checking_protocol"?
                        "LOTUSim protocol preflight timed out: no compatible dataset_control response. No scenario was launched. "+DatasetLotusimProtocol.ReloadHelp:
                        "LOTUSim "+Status+" timed out. Check the running simulator, dataset_control service and ROS TCP endpoint; ownership may be unconfirmed.");
            }
            catch(Exception error) {
                if(Status=="stopping") {CleanupFinished=true;CleanupConfirmed=false;Status="cleanup_unconfirmed";Debug.LogWarning("[LOTUSim Dataset] "+error.Message);}
                else {Error=error.ToString();Status="failed";CancelOwned();}
            }
        }
        public void RequestFrame(int frame)
        {
            if(pending!=null||stopSent) throw new InvalidOperationException("A LOTUSim request is already in flight or stopping.");
            requestedFrame=frame;HasFrame=false;Status="stepping";
            Send(controlService,JsonUtility.ToJson(new Control{operation="step",runId=RunId,frame=frame}));
        }
        public void StopOwned()
        {
            if(stopSent) return;
            if(pending!=null||string.IsNullOrEmpty(RunId)) throw new InvalidOperationException("Cannot confirm dataset ownership for cleanup.");
            stopSent=true;HasFrame=false;Status="stopping";
            Send(controlService,JsonUtility.ToJson(new Control{operation="stop",runId=RunId}));
        }
        public void CancelOwned()
        {
            if(stopSent||ros==null||string.IsNullOrEmpty(RunId)) return;
            stopSent=true;
            // Never use the generic stop_scenario service: a delayed request
            // must not stop a different scenario launched in the meantime.
            ros.SendServiceMessage<DatasetStringResponse>(controlService,new DatasetStringRequest(JsonUtility.ToJson(new Control{operation="stop",runId=RunId})),r=>{
                CleanupFinished=true;CleanupConfirmed=r.success;
            });
        }
        void Send(string service,string data) {since=Time.realtimeSinceStartup;pending=ros.SendServiceMessage<DatasetStringResponse>(service,new DatasetStringRequest(data));}
        void OnDisable() {CancelOwned();}
        [Serializable] sealed class Control {public string operation,runId;public int frame;}
    }
}
