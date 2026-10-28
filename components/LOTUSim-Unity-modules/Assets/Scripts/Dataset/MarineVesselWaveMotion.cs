using System;
using System.Linq;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace Lotusim.Dataset
{
    public enum MarineWaveMode { VisualResponse, FreeRigidbody }
    [Serializable] public sealed class MarineVesselParameters
    {
        public float lengthM=12,beamM=3.8f,draftM=.7f,blockCoefficient=.45f;
        public float waterDensityKgM3=1025,dampingRatio=.85f,maxRollDeg=18,maxPitchDeg=12;
        public float waterlineOffsetM,heaveFrequencyScale=1,angularFrequencyScale=.6f;
        public float MassKg=>waterDensityKgM3*lengthM*beamM*draftM*blockCoefficient;
        public void Validate()
        {
            if(!Range(lengthM,1,400)||!Range(beamM,.5f,lengthM)||!Range(draftM,.05f,25)||!Range(blockCoefficient,.05f,.95f)||
                !Range(waterDensityKgM3,950,1100)||!Range(dampingRatio,.2f,3)||!Range(maxRollDeg,0,35)||!Range(maxPitchDeg,0,30)||
                !Range(waterlineOffsetM,-5,5)||!Range(heaveFrequencyScale,.1f,3)||!Range(angularFrequencyScale,.1f,2))
                throw new ArgumentException("Invalid marine flotation dimensions or response parameters.");
        }
        static bool Range(float v,float a,float b)=>!float.IsNaN(v)&&!float.IsInfinity(v)&&v>=a&&v<=b;
    }
    public static class MarineVesselCatalog
    {
        public static readonly string[] Models={"fishing_trawler","container_ship","motor_yacht","speedboat","jetski","ferry","sailboat"};
        public static readonly string[] DisplayNames={"chalutier","porte-conteneurs","yacht à moteur","hors-bord","jetski","ferry","voilier"};
        public static MarineVesselParameters Parameters(int index)
        {
            var p=new MarineVesselParameters();
            switch(index) {
                case 0:p.lengthM=24;p.beamM=7.2f;p.draftM=2.1f;p.blockCoefficient=.50f;p.maxRollDeg=18;p.maxPitchDeg=10;break;
                case 1:p.lengthM=185;p.beamM=30;p.draftM=8;p.blockCoefficient=.66f;p.maxRollDeg=8;p.maxPitchDeg=4;p.heaveFrequencyScale=.7f;break;
                case 2:p.lengthM=14;p.beamM=4.3f;p.draftM=.75f;p.blockCoefficient=.42f;break;
                case 3:p.lengthM=6.4f;p.beamM=2.4f;p.draftM=.38f;p.blockCoefficient=.42f;p.maxRollDeg=25;p.maxPitchDeg=18;break;
                case 4:p.lengthM=3.2f;p.beamM=1.2f;p.draftM=.20f;p.blockCoefficient=.38f;p.maxRollDeg=30;p.maxPitchDeg=22;break;
                case 5:p.lengthM=72;p.beamM=16.5f;p.draftM=3;p.blockCoefficient=.62f;p.maxRollDeg=10;p.maxPitchDeg=6;break;
                case 6:p.lengthM=11.8f;p.beamM=3.8f;p.draftM=.65f;p.blockCoefficient=.40f;p.maxRollDeg=24;p.maxPitchDeg=15;break;
                default:throw new ArgumentOutOfRangeException(nameof(index));
            }
            return p;
        }
    }

    /// <summary>
    /// Nine-point HDRP wave response. VisualResponse never writes the ROS root.
    /// FreeRigidbody is an opt-in hydrostatic column approximation, not a
    /// validated naval hydrodynamic/propulsion model or a Gazebo physics bridge.
    /// </summary>
    [DisallowMultipleComponent,RequireComponent(typeof(Rigidbody))]
    public sealed class MarineVesselWaveMotion : MonoBehaviour
    {
        public const string VisualChildName="MarineVesselVisual_v1";
        public MarineWaveMode mode=MarineWaveMode.VisualResponse;
        public MarineVesselParameters parameters=new MarineVesselParameters();
        public Transform visual;
        public WaterSurface water;
        public bool autoEnableWaterQueries=true;
        [Range(.2f,3)] public float angularResponseGain=1;
        public bool HasValidSample {get;private set;}
        public int SampleUnityFrame {get;private set;}=-1;
        public float HeaveM {get;private set;}
        public float RollDeg {get;private set;}
        public float PitchDeg {get;private set;}
        public string LastQueryFailure {get;private set;}="Waiting for CPU ocean data.";
        public bool ExternallyDriven {get;private set;}
        Rigidbody body;
        Camera captureCamera;
        Vector3 restPosition;
        Quaternion restRotation;
        readonly Vector3[] candidates=new Vector3[9];
        readonly bool[] candidateValid=new bool[9];
        readonly float[] heights=new float[9];
        readonly Vector3[] samplePoints=new Vector3[9];
        float heave,heaveVelocity,roll,rollVelocity,pitch,pitchVelocity,lastWarning;
        bool initialized,restKnown,configured;

        public void Configure(WaterSurface ocean,Camera camera,bool externallyDriven=true)
        {
            parameters.Validate();water=ocean;captureCamera=camera;
            if(externallyDriven) MarkExternallyDriven();
            EnsureReferences();configured=true;
        }
        public void MarkExternallyDriven()
        {
            ExternallyDriven=true;mode=MarineWaveMode.VisualResponse;
            if(body==null) body=GetComponent<Rigidbody>();
            body.isKinematic=true;body.useGravity=false;
        }
        void EnsureReferences()
        {
            if(angularResponseGain==0) angularResponseGain=1; // Legacy serialized prefabs.
            if(float.IsNaN(angularResponseGain)||angularResponseGain<.2f||angularResponseGain>3) throw new ArgumentException("Invalid vessel angular response gain.");
            parameters.Validate();if(body==null) body=GetComponent<Rigidbody>();
            if(visual==null) visual=transform.Find(VisualChildName);
            if(visual==null||visual==transform||!visual.IsChildOf(transform)) throw new InvalidOperationException("Marine vessels require a separate visual child; root motion belongs to ROS.");
            if(!restKnown) {restPosition=visual.localPosition;restRotation=visual.localRotation;restKnown=true;}
            if(water==null) water=FindObjectsOfType<WaterSurface>().FirstOrDefault(w=>w.isActiveAndEnabled);
            if(water!=null&&autoEnableWaterQueries) {water.cpuSimulation=true;water.cpuFullResolution=true;}
            body.mass=parameters.MassKg;body.centerOfMass=new Vector3(-parameters.lengthM*.04f,-parameters.draftM*.65f,0);
            body.maxAngularVelocity=2;body.interpolation=RigidbodyInterpolation.Interpolate;
        }
        void Start()
        {
            if(!configured) Configure(water,null,false);
            if(mode==MarineWaveMode.VisualResponse) {body.isKinematic=true;body.useGravity=false;}
        }
        void OnEnable() {RenderPipelineManager.beginCameraRendering+=BeforeCamera;}
        void OnDisable()
        {
            RenderPipelineManager.beginCameraRendering-=BeforeCamera;
            if(body!=null) {if(!body.isKinematic) {body.velocity=Vector3.zero;body.angularVelocity=Vector3.zero;}body.isKinematic=true;}
            if(restKnown&&visual!=null) {visual.localPosition=restPosition;visual.localRotation=restRotation;}
            HasValidSample=false;initialized=false;SampleUnityFrame=-1;
            heaveVelocity=rollVelocity=pitchVelocity=0;
        }
        bool Query(int i,Vector3 point)
        {
            if(water==null) {LastQueryFailure="No active HDRP WaterSurface. Enable Water Script Interactions in the HDRP asset.";return false;}
            var query=new WaterSearchParameters{targetPosition=point,startPosition=candidateValid[i]?candidates[i]:point,error=.015f,maxIterations=20};
            if(!water.FindWaterSurfaceHeight(query,out var result)||!Finite(result.height)||!Finite(result.error)||result.error>.08f) {
                candidateValid[i]=false;LastQueryFailure="HDRP CPU water query unavailable/non-convergent. Check Script Interactions.";return false;
            }
            heights[i]=result.height;candidates[i]=result.candidateLocation;candidateValid[i]=true;return true;
        }
        void BeforeCamera(ScriptableRenderContext context,Camera camera)
        {
            if(mode!=MarineWaveMode.VisualResponse||(captureCamera!=null&&camera!=captureCamera)||SampleUnityFrame==Time.frameCount) return;
            if(!configured) return;
            SampleUnityFrame=Time.frameCount;HasValidSample=false;
            Vector3 rest=visual.parent.TransformPoint(restPosition);
            Vector3 forward=Vector3.ProjectOnPlane(transform.right,Vector3.up).normalized;
            Vector3 side=Vector3.Cross(forward,Vector3.up);
            float halfLength=parameters.lengthM*.34f,halfBeam=parameters.beamM*.32f;
            for(int x=0;x<3;x++) for(int z=0;z<3;z++) {
                int i=x*3+z;samplePoints[i]=rest+forward*((x-1)*halfLength)+side*((z-1)*halfBeam);
                if(!Query(i,samplePoints[i])) {WarnOnce();return;}
            }
            float targetHeave=heights.Average()+parameters.waterlineOffsetM-rest.y;
            float slopeForward=((heights[6]+heights[7]+heights[8])-(heights[0]+heights[1]+heights[2]))/(6*halfLength);
            float slopeSide=((heights[2]+heights[5]+heights[8])-(heights[0]+heights[3]+heights[6]))/(6*halfBeam);
            float targetPitch=Mathf.Clamp(-Mathf.Atan(slopeSide)*Mathf.Rad2Deg*angularResponseGain,-parameters.maxRollDeg,parameters.maxRollDeg);
            float targetRoll=Mathf.Clamp(Mathf.Atan(slopeForward)*Mathf.Rad2Deg*angularResponseGain,-parameters.maxPitchDeg,parameters.maxPitchDeg);
            float omega=Mathf.Sqrt(9.81f/parameters.draftM)*parameters.heaveFrequencyScale;
            if(!initialized) {heave=targetHeave;roll=targetRoll;pitch=targetPitch;initialized=true;}
            else {
                Spring(ref heave,ref heaveVelocity,targetHeave,omega,parameters.dampingRatio,Time.deltaTime);
                Spring(ref roll,ref rollVelocity,targetRoll,omega*parameters.angularFrequencyScale,parameters.dampingRatio,Time.deltaTime);
                Spring(ref pitch,ref pitchVelocity,targetPitch,omega*parameters.angularFrequencyScale,parameters.dampingRatio,Time.deltaTime);
            }
            roll=Mathf.Clamp(roll,-parameters.maxPitchDeg,parameters.maxPitchDeg);pitch=Mathf.Clamp(pitch,-parameters.maxRollDeg,parameters.maxRollDeg);
            Quaternion tilt=Quaternion.AngleAxis(roll,side)*Quaternion.AngleAxis(pitch,forward);
            visual.SetPositionAndRotation(rest+Vector3.up*heave,tilt*(visual.parent.rotation*restRotation));
            HeaveM=heave;RollDeg=pitch;PitchDeg=roll;HasValidSample=true;LastQueryFailure="";
        }
        public void SampleForCamera(ScriptableRenderContext context,Camera camera)=>BeforeCamera(context,camera);
        void FixedUpdate()
        {
            if(!configured) return;
            // Inspector mode changes must never leave a previously free body
            // integrating alongside the visual response or a ROS root pose.
            if(mode==MarineWaveMode.VisualResponse||ExternallyDriven) {
                if(!body.isKinematic) {body.velocity=Vector3.zero;body.angularVelocity=Vector3.zero;initialized=false;heaveVelocity=rollVelocity=pitchVelocity=0;}
                body.isKinematic=true;body.useGravity=false;return;
            }
            visual.localPosition=restPosition;visual.localRotation=restRotation;
            HasValidSample=false;
            for(int x=0;x<3;x++) for(int z=0;z<3;z++) {
                int i=x*3+z;samplePoints[i]=transform.TransformPoint(new Vector3((x-1)*parameters.lengthM*.34f,-parameters.draftM,(z-1)*parameters.beamM*.32f));
                if(!Query(i,samplePoints[i])) {
                    if(!body.isKinematic) {body.velocity=Vector3.zero;body.angularVelocity=Vector3.zero;body.isKinematic=true;}
                    WarnOnce();return;
                }
            }
            body.isKinematic=false;body.useGravity=true;body.drag=.1f;body.angularDrag=.5f;
            float gravity=Physics.gravity.magnitude,mass=parameters.MassKg,stiffness=mass*gravity/parameters.draftM;
            float damping=2*parameters.dampingRatio*Mathf.Sqrt(stiffness*mass);
            for(int i=0;i<9;i++) {
                float depth=heights[i]+parameters.waterlineOffsetM-samplePoints[i].y;
                Vector3 velocity=body.GetPointVelocity(samplePoints[i]);
                float force=ColumnForce(mass,gravity,parameters.draftM,depth,velocity.y,damping,9);
                body.AddForceAtPosition(Vector3.up*force,samplePoints[i],ForceMode.Force);
                if(depth>0) body.AddForceAtPosition(-Vector3.ProjectOnPlane(velocity,Vector3.up)*(mass*.18f/9),samplePoints[i],ForceMode.Force);
            }
            HasValidSample=true;LastQueryFailure="";
        }
        void WarnOnce()
        {
            if(Time.realtimeSinceStartup-lastWarning<10) return;lastWarning=Time.realtimeSinceStartup;
            Debug.LogWarning("[Marine flotation] "+name+": "+LastQueryFailure);
        }
        // Stable implicit damped spring, including long editor frames.
        public static void Spring(ref float value,ref float velocity,float target,float omega,float damping,float dt)
        {
            if(dt<=0) return;dt=Mathf.Min(dt,.25f);float f=1+2*dt*damping*omega,a=dt*omega*omega,den=1/(f+dt*a);
            float next=(f*value+dt*velocity+dt*a*target)*den;velocity=(velocity+a*(target-value))*den;value=next;
        }
        public static float ColumnForce(float mass,float gravity,float draft,float depth,float velocityY,float damping,int points)
        {
            if(depth<=0) return 0;
            return Mathf.Max(0,(mass*gravity*Mathf.Clamp(depth/draft,0,3)-damping*velocityY)/points);
        }
        static bool Finite(float v)=>!float.IsNaN(v)&&!float.IsInfinity(v);
    }
}
