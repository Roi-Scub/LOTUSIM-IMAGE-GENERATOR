using System;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;
using Lotusim.Dataset;
using UnityEditor;
using UnityEngine;
using Debug=UnityEngine.Debug;

namespace Lotusim.EditorTools
{
    // Separate offline RGB worker. The independent detector never receives a
    // test pose, annotation or mask. The explicitly localized diagnostic uses
    // Unity boxes in its coordinator; neither mode opens a Unity ROSConnection.
    [InitializeOnLoad] public static class DatasetRgbObserverTools
    {
        const string AutoKey="LOTUSim.RgbObserver.AutoAfterTraffic",GazeboKey="LOTUSim.RgbObserver.GazeboTransport";
        const string KindKey="LOTUSim.RgbObserver.Kind";
        [Serializable] sealed class ValidationPlan {public string knowledgeDirectory,detectorConfig;}
        static Process worker;static Task<string> stdout,stderr;static string lastRun,activeOutput,activeKind;static double next;
        public static string OutputDirectory=>activeOutput??SessionState.GetString("LOTUSim.RgbObserver.Output","");
        static string JobKind=>activeKind??SessionState.GetString(KindKey,"Independent RGB analysis");
        public static bool Running=>worker!=null&&!worker.HasExited;
        static DatasetRgbObserverTools(){Restore();EditorApplication.update+=Tick;}
        static void Restore()
        {
            if(Application.isBatchMode)return;
            int pid=SessionState.GetInt("LOTUSim.RgbObserver.Pid",0);if(pid==0)return;
            try {
                var process=Process.GetProcessById(pid);
                if(process.HasExited||process.StartTime.ToUniversalTime().Ticks.ToString()!=SessionState.GetString("LOTUSim.RgbObserver.StartTime","")){process.Dispose();return;}
                worker=process;activeOutput=SessionState.GetString("LOTUSim.RgbObserver.Output","");activeKind=SessionState.GetString(KindKey,"Independent RGB analysis");
            }catch(ArgumentException){}catch(InvalidOperationException){}catch(System.ComponentModel.Win32Exception){}
        }
        [MenuItem("LOTUSim/Dataset/RGB observer/Automatic analysis after traffic sequence")]
        static void ToggleAuto(){EditorPrefs.SetBool(AutoKey,!EditorPrefs.GetBool(AutoKey,true));}
        [MenuItem("LOTUSim/Dataset/RGB observer/Automatic analysis after traffic sequence",true)]
        static bool AutoChecked(){Menu.SetChecked("LOTUSim/Dataset/RGB observer/Automatic analysis after traffic sequence",EditorPrefs.GetBool(AutoKey,true));return true;}
        [MenuItem("LOTUSim/Dataset/RGB observer/Pass RGB through Gazebo Transport")]
        static void ToggleGazebo(){EditorPrefs.SetBool(GazeboKey,!EditorPrefs.GetBool(GazeboKey,true));}
        [MenuItem("LOTUSim/Dataset/RGB observer/Pass RGB through Gazebo Transport",true)]
        static bool GazeboChecked(){Menu.SetChecked("LOTUSim/Dataset/RGB observer/Pass RGB through Gazebo Transport",EditorPrefs.GetBool(GazeboKey,true));return true;}
        [MenuItem("LOTUSim/Dataset/RGB observer/Analyze an existing capture folder")]
        static void Choose(){string folder=EditorUtility.OpenFolderPanel("Choisir le dossier de campagne contenant rgb/",Path.Combine(Application.dataPath,"..","artifacts"),"");if(!string.IsNullOrEmpty(folder))Start(folder);}
        [MenuItem("LOTUSim/Dataset/RGB observer/Verify Unity-localized instances (diagnostic)")]
        static void ChooseLocalized()
        {
            string folder=EditorUtility.OpenFolderPanel("Vérifier des objets localisés par Unity — choisir une campagne annotée",Path.Combine(Application.dataPath,"..","artifacts"),"");
            if(!string.IsNullOrEmpty(folder))StartLocalized(folder);
        }
        [MenuItem("LOTUSim/Dataset/RGB observer/Verify Unity-localized instances (diagnostic)",true)]
        static bool LocalizedEnabled()=>!EditorApplication.isPlayingOrWillChangePlaymode&&!Running;
        [MenuItem("LOTUSim/Dataset/RGB observer/Open last visual report")]
        static void OpenLastReport(){string gallery=Path.Combine(OutputDirectory,"index.html");if(File.Exists(gallery))EditorUtility.OpenWithDefaultApp(gallery);}
        [MenuItem("LOTUSim/Dataset/RGB observer/Open last visual report",true)]
        static bool ReportAvailable()=>File.Exists(Path.Combine(OutputDirectory,"index.html"));
        static string Quote(string value)=>"\""+value.Replace("\\","\\\\").Replace("\"","\\\"")+"\"";
        static string CorePath(string core,string value)=>Path.GetFullPath(Path.IsPathRooted(value)?value:Path.Combine(core,value));
        public static void Start(string campaign)
        {
            if(Application.isBatchMode)return;
            if(Running){Debug.LogWarning("[RGB Observer] An independent analysis is already running; no duplicate worker started.");return;}
            string core=DatasetTrafficAgentsBuilder.CoreRoot,python=Path.Combine(core,".venv-vision",Application.platform==RuntimePlatform.WindowsEditor?"Scripts/python.exe":"bin/python");
            string script=Path.Combine(core,"tools/rgb_observer.py");
            if(!File.Exists(python)||!File.Exists(script)||!Directory.Exists(Path.Combine(campaign,"rgb"))){Debug.LogError("[RGB Observer] Local detector or clean rgb/ folder missing. See docs/guide-visibilite-agent-rgb.md in LOTUSim.");return;}
            activeOutput=Path.Combine(campaign,"visual-observer",DateTime.UtcNow.ToString("yyyyMMdd_HHmmss")+"_"+Guid.NewGuid().ToString("N").Substring(0,8));
            var info=new ProcessStartInfo{FileName=python,Arguments=Quote(script)+" --rgb "+Quote(Path.Combine(campaign,"rgb"))+" --output "+Quote(activeOutput)+" --compare"+(EditorPrefs.GetBool(GazeboKey,true)?" --via-gazebo":""),WorkingDirectory=core,UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true};
            Launch(info,campaign,"Independent RGB analysis",true);
            Debug.Log("[RGB Observer] Independent RGB analysis started after capture; no additional ROS TCP client. Output: "+activeOutput);
        }
        public static void StartLocalized(string campaign)
        {
            if(Application.isBatchMode)return;
            if(EditorApplication.isPlayingOrWillChangePlaymode){Debug.LogWarning("[RGB Observer] Quit Play before starting the bounded localized diagnostic. No simulation was changed.");return;}
            if(Running){Debug.LogWarning("[RGB Observer] A visual analysis is already running; no duplicate worker started.");return;}
            try {
                string core=DatasetTrafficAgentsBuilder.CoreRoot,python=Path.Combine(core,".venv-vision",Application.platform==RuntimePlatform.WindowsEditor?"Scripts/python.exe":"bin/python");
                string script=Path.Combine(core,"tools/rgb_verify_instances.py"),planFile=Path.Combine(core,"assets/perception/rgb_validation.json");
                if(!File.Exists(python)||!File.Exists(script)||!File.Exists(planFile))throw new FileNotFoundException("Local visual verification tools/configuration are missing. See docs/guide-validation-visuelle-rgb.md in LOTUSim.");
                var plan=JsonUtility.FromJson<ValidationPlan>(File.ReadAllText(planFile));
                if(plan==null||string.IsNullOrWhiteSpace(plan.knowledgeDirectory)||string.IsNullOrWhiteSpace(plan.detectorConfig))throw new InvalidDataException("rgb_validation.json must define knowledgeDirectory and detectorConfig.");
                string knowledge=CorePath(core,plan.knowledgeDirectory),config=CorePath(core,plan.detectorConfig);
                string knowledgeRoot=Path.GetFileName(knowledge)=="public"?Path.GetDirectoryName(knowledge):knowledge;
                if(!File.Exists(Path.Combine(knowledgeRoot,"public/index.json"))||!File.Exists(Path.Combine(knowledgeRoot,"coordinator/provenance.json")))throw new FileNotFoundException("Build the visual knowledge base first; its public index and coordinator provenance are required. See docs/guide-validation-visuelle-rgb.md.");
                if(!File.Exists(config))throw new FileNotFoundException("The detector/encoder configuration from rgb_validation.json is missing.");
                campaign=Path.GetFullPath(campaign);
                if(Path.GetFileName(campaign)=="rgb")campaign=Path.GetDirectoryName(campaign);
                if(!Directory.Exists(Path.Combine(campaign,"rgb"))||(!Directory.Exists(Path.Combine(campaign,"annotations"))&&!File.Exists(Path.Combine(campaign,"annotations.coco.json"))))throw new DirectoryNotFoundException("Select an annotated campaign containing clean rgb/ and annotations/ or annotations.coco.json.");
                activeOutput=Path.Combine(campaign,"visual-verification",DateTime.UtcNow.ToString("yyyyMMdd_HHmmss")+"_"+Guid.NewGuid().ToString("N").Substring(0,8));
                var info=new ProcessStartInfo{FileName=python,Arguments=Quote(script)+" --campaign "+Quote(campaign)+" --knowledge "+Quote(knowledge)+" --config "+Quote(config)+" --output "+Quote(activeOutput)+" --limit 4 --max-objects 12",WorkingDirectory=core,UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true};
                Launch(info,campaign,"Unity-localized classification diagnostic",false);
                Debug.Log("[RGB Observer] Localized diagnostic started: up to 4 frames / 12 objects, with Unity-provided boxes. This is NOT independent detection or calibrated certainty. No ROS/Gazebo connection opened. Output: "+activeOutput);
            }catch(Exception error){Debug.LogError("[RGB Observer] Localized diagnostic was not started. "+error.Message);}
        }
        static void Launch(ProcessStartInfo info,string campaign,string kind,bool recordDetectionRun)
        {
            worker=Process.Start(info);stdout=worker.StandardOutput.ReadToEndAsync();stderr=worker.StandardError.ReadToEndAsync();activeKind=kind;
            SessionState.SetString("LOTUSim.RgbObserver.Output",activeOutput);SessionState.SetString(KindKey,kind);
            if(recordDetectionRun){SessionState.SetString("LOTUSim.RgbObserver.LastRun",campaign);lastRun=campaign;}
            SessionState.SetInt("LOTUSim.RgbObserver.Pid",worker.Id);SessionState.SetString("LOTUSim.RgbObserver.StartTime",worker.StartTime.ToUniversalTime().Ticks.ToString());
        }
        static void Tick()
        {
            if(Application.isBatchMode||EditorApplication.timeSinceStartup<next)return;next=EditorApplication.timeSinceStartup+.5;
            if(worker!=null&&worker.HasExited){
                int code=worker.ExitCode;string errors=stderr==null?"See the observer status.json file.":stderr.GetAwaiter().GetResult();stdout?.GetAwaiter().GetResult();worker.Dispose();worker=null;stdout=stderr=null;SessionState.SetInt("LOTUSim.RgbObserver.Pid",0);
                if(code==0)Debug.Log("[RGB Observer] "+JobKind+" COMPLETE: "+Path.Combine(OutputDirectory,"index.html"));
                else Debug.LogError("[RGB Observer] "+JobKind+" FAILED; capture files preserved. "+(errors.Length>1800?errors.Substring(errors.Length-1800):errors));
            }
            if(Running||!EditorPrefs.GetBool(AutoKey,true))return;
            var runner=UnityEngine.Object.FindObjectOfType<DatasetSequenceRunner>();
            if(runner==null||runner.configuration==null||runner.configuration.ScenarioName!=DatasetTrafficAgentsBuilder.Name||
                (runner.Status!="complete"&&runner.Status!="complete_cleanup_unconfirmed")||string.IsNullOrEmpty(runner.OutputDirectory))return;
            string seen=lastRun??SessionState.GetString("LOTUSim.RgbObserver.LastRun","");if(seen==runner.OutputDirectory)return;
            lastRun=runner.OutputDirectory;Start(runner.OutputDirectory);
        }
        public static void Draw(string campaign)
        {
            GUILayout.Space(8);GUILayout.Label("Agent visuel indépendant · RGB uniquement",EditorStyles.boldLabel);
            GUILayout.Label(Running?JobKind+" en cours (séparé de la capture).":"Les annotations Unity et les prédictions visuelles sont deux résultats distincts.",EditorStyles.wordWrappedLabel);
            if(GUILayout.Button("Analyser les RGB avec l'agent indépendant"))Start(campaign);
            string gallery=Path.Combine(OutputDirectory,"index.html");if(File.Exists(gallery)&&GUILayout.Button("Ouvrir le rapport visuel"))EditorUtility.OpenWithDefaultApp(gallery);
        }
    }
}
