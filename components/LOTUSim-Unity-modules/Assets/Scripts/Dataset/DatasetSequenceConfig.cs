using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace Lotusim.Dataset
{
    [Serializable] public sealed class DatasetSeaEvolution
    {
        public bool enabled;
        public float periodSeconds=22,minWindKmh=52,maxWindKmh=95,minBand=.78f,maxBand=1;
        public float patchSizeM=384,directionDeg=35;
        public void Validate()
        {
            if(!Range(periodSeconds,8,180)||!Range(minWindKmh,30,110)||!Range(maxWindKmh,minWindKmh,120)||
                !Range(minBand,.1f,1)||!Range(maxBand,minBand,1)||!Range(patchSizeM,128,1024)||!Range(directionDeg,0,360))
                throw new ArgumentException("Invalid evolving swell ranges.");
        }
        public DatasetSeaPreset Evaluate(float time,int seed)
        {
            float phase=(seed%997)*.0063f;
            float level=.5f+.34f*Mathf.Sin(2*Mathf.PI*time/periodSeconds+phase)+.16f*Mathf.Sin(2*Mathf.PI*time/(periodSeconds*2.7f)+phase*.37f);
            level=Mathf.Clamp01(level);
            return new DatasetSeaPreset{name="evolving_agitated_swell",windKmh=Mathf.Lerp(minWindKmh,maxWindKmh,level),band0=Mathf.Lerp(minBand,maxBand,level),
                band1=Mathf.Lerp(minBand*.9f,maxBand,level),ripplesKmh=Mathf.Lerp(12,25,level),foam=Mathf.Lerp(.25f,.65f,level),patchSizeM=patchSizeM,
                directionDeg=directionDeg+8*Mathf.Sin(2*Mathf.PI*time/(periodSeconds*3)+phase),cameraMotionScale=Mathf.Lerp(.7f,1,level)};
        }
        static bool Range(float v,float a,float b)=>!float.IsNaN(v)&&!float.IsInfinity(v)&&v>=a&&v<=b;
    }
    [Serializable] public sealed class DatasetLightingPhase
    {
        public int startFrame,endFrame;
        public string timeOfDay;
        public DatasetLightPreset light;
    }
    [Serializable] public sealed class DatasetSequenceLightingSettings
    {
        [Tooltip("Use balanced day/evening/full-moon blocks, starting in daylight. Disabled preserves the standalone randomizer.")]
        public bool cycleDayEveningNight;
        [Range(2,60)] public int settleFrames=4;
        public DatasetLightPreset day=new DatasetLightPreset{name="day",illuminant="sun",relativeBearingDeg=-35,elevationDeg=40,intensityLux=80000,exposureEV100=13,temperatureKelvin=5600};
        public DatasetLightPreset evening=new DatasetLightPreset{name="evening",illuminant="sun",relativeBearingDeg=-70,elevationDeg=12,intensityLux=8000,exposureEV100=9,temperatureKelvin=4200};
        public DatasetLightPreset night=new DatasetLightPreset{name="night",illuminant="full_moon",relativeBearingDeg=-135,elevationDeg=35,intensityLux=.3f,exposureEV100=-4,temperatureKelvin=7500};
        public void Validate()
        {
            if(settleFrames<2||settleFrames>60) throw new ArgumentException("Lighting settle frames must be 2–60.");
            foreach(var light in new[]{day,evening,night})
                if(light==null||string.IsNullOrWhiteSpace(light.name)||string.IsNullOrWhiteSpace(light.illuminant)||
                    !Range(light.relativeBearingDeg,-180,180)||!Range(light.elevationDeg,3,85)||!Range(light.intensityLux,.001f,150000)||
                    !Range(light.exposureEV100,-8,20)||!Range(light.temperatureKelvin,2000,12000))
                    throw new ArgumentException("Invalid day/evening/night lighting preset. Lower EV100 gives a brighter exposure.");
        }
        public DatasetLightingPhase[] Build(int frames,int captureEveryFrames)
        {
            Validate();int images=(frames+captureEveryFrames-1)/captureEveryFrames;
            if(images<3) throw new ArgumentException("Day/evening/night needs at least three captures.");
            int a=((images+2)/3)*captureEveryFrames,b=((2*images+2)/3)*captureEveryFrames;
            return new[]{new DatasetLightingPhase{startFrame=0,endFrame=a,timeOfDay="12:00",light=day},
                new DatasetLightingPhase{startFrame=a,endFrame=b,timeOfDay="18:30",light=evening},
                new DatasetLightingPhase{startFrame=b,endFrame=frames,timeOfDay="23:00",light=night}};
        }
        static bool Range(float value,float min,float max)=>!float.IsNaN(value)&&!float.IsInfinity(value)&&value>=min&&value<=max;
    }
    [Serializable] public sealed class DatasetEncounterClass
    {
        public string category,displayName;
        public int classId,count;
        public GameObject prefab;
        [Tooltip("Optional additional appearances of this SAME category. Empty preserves the original prefab. Selection is deterministic per seed/track.")]
        public GameObject[] prefabVariants=Array.Empty<GameObject>();
        public bool moored;
        public Vector2 distanceM,altitudeM,speedMps;
        public float separationM;
    }
    [Serializable] public sealed class DatasetEncounter
    {
        public string instance,category,modelName;
        public int trackId,classIndex;
        public float startSeconds,endSeconds,centerSeconds,distanceRequestedM,altitudeM;
        public Vector3 centerPosition,velocity;
        public float phase;
        public string flightMode;
        public bool boundedTurn;
        public float yawRateDegS,turnStartSeconds,turnEndSeconds;
        public bool Active(float time) => time>=startSeconds&&time<endSeconds;
        float TurnTime(float time)=>boundedTurn?Mathf.Clamp(time,turnStartSeconds,turnEndSeconds):time;
        public Vector3 Velocity(float time)=>Quaternion.Euler(0,yawRateDegS*(TurnTime(time)-centerSeconds),0)*velocity;
        public Vector3 Position(float time)
        {
            float dt=time-centerSeconds,w=yawRateDegS*Mathf.Deg2Rad;if(Mathf.Abs(w)<1e-9f)return centerPosition+velocity*dt;
            float q=TurnTime(time)-centerSeconds,a=w*q;
            var delta=new Vector3((velocity.x*Mathf.Sin(a)+velocity.z*(1-Mathf.Cos(a)))/w,velocity.y*dt,(velocity.x*(Mathf.Cos(a)-1)+velocity.z*Mathf.Sin(a))/w);
            if(boundedTurn){var before=Velocity(turnStartSeconds);var after=Velocity(turnEndSeconds);before.y=after.y=0;delta+=before*Mathf.Min(0,time-turnStartSeconds)+after*Mathf.Max(0,time-turnEndSeconds);}
            return centerPosition+delta;
        }
        public float VisualBankDeg(float time)
        {
            if(!boundedTurn||time<turnStartSeconds||time>turnEndSeconds)return 0;
            float ramp=Mathf.SmoothStep(0,1,Mathf.Min(time-turnStartSeconds,turnEndSeconds-time)/.6f);
            return -Mathf.Clamp(Mathf.Atan(velocity.magnitude*yawRateDegS*Mathf.Deg2Rad/9.81f)*Mathf.Rad2Deg,-45,45)*ramp;
        }
    }
    [Serializable] public sealed class DatasetSequencePlan
    {
        public string schema="lotusim-unity-encounters-1",motionSource="Unity kinematic; no live ROS",northAxis="Unity +Z",eastAxis="Unity +X";
        public int seed,maxActive;
        public DatasetEncounter[] events;
        public DatasetSeaPreset sea;
        public DatasetLightPreset light;
        public DatasetLightingPhase[] lightingPhases;
        public DatasetSeaEvolution seaEvolution;
        public DatasetTrafficMetadata traffic;
        public DatasetManualImageMetadata manual;
        public int[] captureFrames=Array.Empty<int>();
        public int LightingPhaseAt(int frame)
        {
            if(lightingPhases==null||lightingPhases.Length==0) return 0;
            for(int i=0;i<lightingPhases.Length;i++) if(frame>=lightingPhases[i].startFrame&&frame<lightingPhases[i].endFrame) return i;
            throw new ArgumentOutOfRangeException(nameof(frame),"Frame outside the planned lighting schedule.");
        }
    }
    [CreateAssetMenu(menuName="LOTUSim/Dataset/Randomized maritime sequence")]
    public sealed class DatasetSequenceConfig : ScriptableObject
    {
        public int seed=20261014,width=1280,height=720,simulationFps=30,captureEveryFrames=5,warmupFrames=60;
        public string scenarioName="";
        public int[] captureFrames=Array.Empty<int>();
        public float farClipM=10000;
        public DatasetTrafficPlanBundle trafficPlan;
        public DatasetManualPlanBundle manualPlan;
        public string ScenarioName=>string.IsNullOrEmpty(scenarioName)?DatasetLotusimScenario.Name:scenarioName;
        public float durationSeconds=60,verticalFovDeg=55,observerSpeedMps=4,observerHeightM=3.5f;
        public float routeHeadingDeg=0,viewHeadingDeg=0,viewDownPitchDeg=2;
        [Tooltip("Total smooth heading change over the sequence; negative turns to port. Zero preserves the straight route.")]
        public float observerTurnDeg;
        public bool observerDeckCamera;
        [Tooltip("FREMM root coordinates: X forward, Y up, Z port. Eye height is absolute above the waterline.")]
        public Vector3 observerDeckOffsetM=new Vector3(60,8.85f,-3);
        public string observerCameraStation="foredeck";
        public float observerWaveTiltGain=1.8f,observerMaxRollDeg=7,observerMaxPitchDeg=4;
        [HideInInspector] public int connectedBridgeVersion;
        [Tooltip("Disable calm draws for the connected voyage; standalone legacy defaults remain unchanged.")]
        public bool requireSwell;
        public DatasetSeaEvolution seaEvolution=new DatasetSeaEvolution();
        [HideInInspector] public int connectedVoyageVersion;
        public Vector3 origin=Vector3.zero;
        [Tooltip("Observer hull half extents: beam/2, height, length/2. Zero preserves the small-boat planner.")]
        public Vector3 observerHullHalfExtentsM=Vector3.zero;
        public int maxActiveObjects=12;
        public float maxRollDeg=2.5f,maxPitchDeg=1.5f,waterTiltGain=.4f,heaveGain=.45f,maxHeaveM=1.2f,responsePerSecond=2;
        public float renderTimeoutSeconds=45;
        public string outputRoot="artifacts/dataset-sequences";
        public DatasetAnnotationSettings annotations=new DatasetAnnotationSettings();
        public DatasetFlotationSettings flotation=new DatasetFlotationSettings();
        public DatasetWaterOpticsSettings waterOptics=new DatasetWaterOpticsSettings();
        public DatasetLanternSettings lantern=new DatasetLanternSettings();
        public DatasetSequenceLightingSettings lighting=new DatasetSequenceLightingSettings();
        public DatasetSensorSettings sensors=new DatasetSensorSettings();
        [HideInInspector] public int connectedSensorsVersion;
        [HideInInspector] public int connectedLightingVersion;
        public DatasetEncounterClass[] classes={
            new DatasetEncounterClass{category="buoy",displayName="bouée",classId=1,count=3,moored=true,distanceM=new Vector2(20,70),altitudeM=Vector2.zero,speedMps=Vector2.zero,separationM=5},
            new DatasetEncounterClass{category="drone",displayName="drone",classId=2,count=2,distanceM=new Vector2(20,55),altitudeM=new Vector2(6,18),speedMps=new Vector2(3,7),separationM=3},
            new DatasetEncounterClass{category="helicopter",displayName="hélicoptère",classId=3,count=1,distanceM=new Vector2(280,700),altitudeM=new Vector2(40,110),speedMps=new Vector2(25,45),separationM=20},
            new DatasetEncounterClass{category="airplane",displayName="avion",classId=4,count=1,distanceM=new Vector2(750,1600),altitudeM=new Vector2(160,350),speedMps=new Vector2(50,70),separationM=30},
            new DatasetEncounterClass{category="bird",displayName="oiseau",classId=5,count=4,distanceM=new Vector2(25,110),altitudeM=new Vector2(3,22),speedMps=new Vector2(8,14),separationM=1}
        };
        public int SimulationFrames=>Mathf.CeilToInt(durationSeconds*simulationFps);
        public int ImageCount=>captureFrames!=null&&captureFrames.Length>0?captureFrames.Length:(SimulationFrames+captureEveryFrames-1)/captureEveryFrames;
        public bool ShouldCapture(int frame)=>captureFrames!=null&&captureFrames.Length>0?Array.BinarySearch(captureFrames,frame)>=0:frame%captureEveryFrames==0;
        public static Vector3 Bearing(float heading) => new Vector3(Mathf.Sin(heading*Mathf.Deg2Rad),0,Mathf.Cos(heading*Mathf.Deg2Rad));
        public float ObserverHeading(float time)=>routeHeadingDeg+observerTurnDeg*Mathf.Clamp01(time/durationSeconds);
        public float ViewHeading(float time)=>viewHeadingDeg+observerTurnDeg*Mathf.Clamp01(time/durationSeconds);
        public Vector3 ObserverRoot(float time)
        {
            float t=Mathf.Clamp(time,0,durationSeconds),theta=routeHeadingDeg*Mathf.Deg2Rad,w=observerTurnDeg*Mathf.Deg2Rad/durationSeconds;
            if(Mathf.Abs(w)<1e-7f) return origin+Bearing(routeHeadingDeg)*(observerSpeedMps*t);
            return origin+new Vector3((Mathf.Cos(theta)-Mathf.Cos(theta+w*t))/w,0,(Mathf.Sin(theta+w*t)-Mathf.Sin(theta))/w)*observerSpeedMps;
        }
        public Vector3 ObserverNominal(float time)
        {
            if(!observerDeckCamera) return ObserverRoot(time)+Vector3.up*observerHeightM;
            return ObserverRoot(time)+Bearing(ObserverHeading(time))*observerDeckOffsetM.x+Vector3.up*observerDeckOffsetM.y-Bearing(ObserverHeading(time)+90)*observerDeckOffsetM.z;
        }
        public void Validate(bool requirePrefabs=true)
        {
            if(trafficPlan!=null&&manualPlan!=null)throw new ArgumentException("A sequence cannot mix traffic and manual plans.");
            if(captureFrames!=null&&captureFrames.Length>0&&((trafficPlan==null&&manualPlan==null)||captureFrames.Length>SimulationFrames||captureFrames.Where((v,i)=>v<0||v>=SimulationFrames||i>0&&v<=captureFrames[i-1]).Any()))throw new ArgumentException("Invalid compiled capture schedule.");
            if(width<64||height<64||width>4096||height>4096||simulationFps<1||simulationFps>60||captureEveryFrames<1||warmupFrames<2||
                !In(durationSeconds,4,600)||!In(verticalFovDeg,30,90)||!In(observerSpeedMps,0,15)||!In(observerHeightM,2,80)||
                !In(observerHullHalfExtentsM.x,0,100)||!In(observerHullHalfExtentsM.y,0,100)||!In(observerHullHalfExtentsM.z,0,200)||
                !In(routeHeadingDeg,0,359.999f)||!In(viewHeadingDeg,0,359.999f)||!In(viewDownPitchDeg,-10,15)||
                !In(observerTurnDeg,-20,20)||(observerDeckCamera&&(!In(observerDeckOffsetM.x,-70,70)||!In(observerDeckOffsetM.y,2,45)||!In(observerDeckOffsetM.z,-15,15)))||
                (observerDeckCamera&&(!In(observerWaveTiltGain,.2f,3)||!In(observerMaxRollDeg,0,12)||!In(observerMaxPitchDeg,0,8)))||
                !In(maxRollDeg,0,5)||!In(maxPitchDeg,0,5)||!In(waterTiltGain,0,1)||!In(heaveGain,0,1)||!In(maxHeaveM,0,3)||
                !In(responsePerSecond,.1f,20)||!In(renderTimeoutSeconds,1,300)||maxActiveObjects<1||maxActiveObjects>(trafficPlan==null&&manualPlan==null?24:40)||!In(farClipM,5000,100000)||
                !Finite(origin.x)||!Finite(origin.y)||!Finite(origin.z)||string.IsNullOrWhiteSpace(outputRoot)) throw new ArgumentException("Invalid sequence camera, timing or capacity settings.");
            if(ScenarioName.Length>64||!char.IsLetter(ScenarioName[0])||ScenarioName.Any(ch=>!char.IsLetterOrDigit(ch)&&ch!='_'))throw new ArgumentException("Invalid scenario name.");
            if(classes==null||classes.Length==0||classes.Any(c=>c==null||string.IsNullOrWhiteSpace(c.category)||string.IsNullOrWhiteSpace(c.displayName)||
                c.category.Any(ch=>!char.IsLetterOrDigit(ch)&&ch!='_')||c.classId<1||c.count<0||c.count>12||!Range(c.distanceM,5,trafficPlan==null&&manualPlan==null?5000:60000)||!Range(c.altitudeM,0,trafficPlan==null&&manualPlan==null?2000:15000)||!Range(c.speedMps,0,trafficPlan==null&&manualPlan==null?200:350)||
                !In(c.separationM,.1f,200)||(c.moored?c.speedMps!=Vector2.zero:c.speedMps.x<=0)||(requirePrefabs&&c.prefab==null))) throw new ArgumentException("Invalid encounter classes/ranges or missing prefabs.");
            if(classes.Sum(c=>c.count)<1||classes.Sum(c=>c.count)>40||classes.Select(c=>c.classId).Distinct().Count()!=classes.Length||
                classes.Select(c=>c.category).Distinct().Count()!=classes.Length) throw new ArgumentException("Class IDs/names must be unique; request 1–40 encounters.");
            foreach(var c in classes) if(c.prefabVariants!=null&&c.prefabVariants.Length>0) {
                if(c.prefab==null||c.prefabVariants.Any(p=>p==null)||c.prefabVariants.Select(p=>p.name).Concat(new[]{c.prefab.name}).Distinct().Count()!=c.prefabVariants.Length+1)
                    throw new ArgumentException("Prefab variants must be non-null, uniquely named and distinct from the default: "+c.category);
                foreach(var p in c.prefabVariants) {
                    if(!DatasetExternalAssetCatalog.Matches(p.name,c.category)) throw new ArgumentException("Variant category mismatch: "+p.name);
                }
            }
            if(annotations==null||flotation==null||waterOptics==null||lantern==null) throw new ArgumentException("Sequence annotation/water settings missing.");
            annotations.Validate();if(!annotations.enabled) throw new ArgumentException("Sequence annotations must be enabled.");
            flotation.Validate();waterOptics.Validate();lantern.Validate();
            if(seaEvolution!=null&&seaEvolution.enabled) seaEvolution.Validate();
            if(sensors!=null) sensors.Validate();
            if(lighting!=null&&lighting.cycleDayEveningNight) {lighting.Validate();if(ImageCount<3) throw new ArgumentException("Day/evening/night requires at least three captures.");}
        }
        public DatasetSequencePlan MakePlan()
        {
            Validate(false);if(manualPlan!=null)return manualPlan.Read(this);if(trafficPlan!=null)return trafficPlan.Read(this);
            var random=new System.Random(seed);var events=new List<DatasetEncounter>();
            float horizontal=Mathf.Tan(verticalFovDeg*Mathf.Deg2Rad/2)*width/height;
            float maxElevation=Mathf.Max(5,verticalFovDeg/2-viewDownPitchDeg-5)*Mathf.Deg2Rad;
            for(int classIndex=0;classIndex<classes.Length;classIndex++) for(int n=0;n<classes[classIndex].count;n++) {
                var c=classes[classIndex];bool accepted=false;
                for(int attempt=0;attempt<256&&!accepted;attempt++) {
                    float focus=Between(random,new Vector2(durationSeconds*.12f,durationSeconds*.88f));
                    float altitude=Between(random,c.altitudeM),distance=Between(random,c.distanceM);
                    float minDistance=Mathf.Max(c.distanceM.x,(altitude-observerHeightM+2)/Mathf.Tan(maxElevation));
                    if(observerHullHalfExtentsM!=Vector3.zero) {
                        float downElevation=Mathf.Max(5,verticalFovDeg/2+viewDownPitchDeg-5)*Mathf.Deg2Rad;
                        minDistance=Mathf.Max(minDistance,(observerHeightM-altitude+2)/Mathf.Tan(downElevation));
                    }
                    if(minDistance>c.distanceM.y) continue;
                    distance=Mathf.Max(distance,minDistance);
                    var forward=Bearing(ViewHeading(focus));var right=Bearing(ViewHeading(focus)+90);
                    float speed=Between(random,c.speedMps),sign=random.Next(2)==0?-1:1;
                    Vector3 center=ObserverNominal(focus)+forward*distance;
                    center.y=origin.y+altitude;
                    if(c.moored) center+=right*Between(random,new Vector2(-.35f,.35f))*horizontal*distance;
                    Vector3 velocity=c.moored?Vector3.zero:right*(speed*sign);
                    Vector3 relativeVelocity=velocity-Bearing(ObserverHeading(focus))*observerSpeedMps;
                    float u=Mathf.Abs(Vector3.Dot(relativeVelocity,right)),w=Vector3.Dot(relativeVelocity,forward),overscan=horizontal*1.25f;
                    float entryDenominator=u+overscan*w,exitDenominator=u-overscan*w;
                    // Solve projected entry/exit with observer translation included.
                    // If no off-screen entry exists, the actor is already present at t=0.
                    float start=c.moored||entryDenominator<=.001f?0:Mathf.Max(0,focus-(overscan*distance+15)/entryDenominator);
                    float end=c.moored||exitDenominator<=.001f?durationSeconds:Mathf.Min(durationSeconds,focus+(overscan*distance+15)/exitDenominator);
                    if(Mathf.Abs(observerTurnDeg)>.0001f&&!c.moored) {
                        // Search the actual curved camera frustum. Do not pop a
                        // crossing actor into view using straight-route times.
                        float first=durationSeconds,last=0,dt=1f/simulationFps;
                        for(int f=0;f<SimulationFrames;f++) {
                            float t=f*dt;var relative=center+velocity*(t-focus)-ObserverNominal(t);
                            float depth=Vector3.Dot(relative,Bearing(ViewHeading(t)));
                            if(depth>0&&Mathf.Abs(Vector3.Dot(relative,Bearing(ViewHeading(t)+90)))<horizontal*1.35f*depth+c.separationM) {first=Mathf.Min(first,t);last=t;}
                        }
                        if(first>last) continue;
                        start=Mathf.Max(0,first-2*dt);end=Mathf.Min(durationSeconds,last+2*dt);
                    }
                    var e=new DatasetEncounter{trackId=events.Count+1,classIndex=classIndex,category=c.category,
                        instance=c.category+"_"+(n+1).ToString("D3"),centerSeconds=focus,centerPosition=center,
                        velocity=velocity,startSeconds=start,
                        endSeconds=end,distanceRequestedM=distance,altitudeM=altitude,
                        phase=Between(random,new Vector2(0,2*Mathf.PI))};
                    var observer=new DatasetEncounter{centerPosition=ObserverNominal(0),velocity=Bearing(routeHeadingDeg)*observerSpeedMps,startSeconds=0,endSeconds=durationSeconds};
                    if(c.moored) observer.centerPosition.y=origin.y; // Keep the route clear in the horizontal sea plane.
                    if(Mathf.Abs(observerTurnDeg)<.0001f&&TooClose(e,observer,Mathf.Max(5,c.separationM),durationSeconds)) continue;
                    if(IntersectsObserverHull(e,c.separationM)) continue;
                    if(events.Any(other=>TooClose(e,other,Mathf.Max(c.separationM,classes[other.classIndex].separationM),durationSeconds))) continue;
                    var trial=events.Concat(new[]{e}).ToArray();
                    if(MaxActive(trial,durationSeconds)>maxActiveObjects) continue;
                    e.modelName=DatasetBoatVariants.Select(c,seed,e.trackId);
                    events.Add(e);accepted=true;
                }
                if(!accepted) throw new InvalidOperationException("Cannot place encounter for "+c.category+" within separation/capacity constraints. Reduce counts or increase duration.");
            }
            var seas=new[]{new DatasetSeaPreset{name="calm",windKmh=0,band0=0,band1=0,ripplesKmh=2,foam=0,cameraMotionScale=.15f},
                new DatasetSeaPreset{name="moderate",windKmh=35,band0=.7f,band1=.6f,ripplesKmh=10,foam=.2f,patchSizeM=192,cameraMotionScale=.65f},
                new DatasetSeaPreset{name="rough",windKmh=70,band0=1,band1=.9f,ripplesKmh=18,foam=.5f,patchSizeM=256}};
            var lights=new[]{new DatasetLightPreset{name="day",relativeBearingDeg=-35,elevationDeg=40,intensityLux=80000,exposureEV100=13,temperatureKelvin=5600},
                new DatasetLightPreset{name="backlight",relativeBearingDeg=180,elevationDeg=12,intensityLux=30000,exposureEV100=12.5f,temperatureKelvin=4500},
                new DatasetLightPreset{name="dusk",relativeBearingDeg=-70,elevationDeg=3,intensityLux=500,exposureEV100=7.5f,temperatureKelvin=3500}};
            var sea=seas[requireSwell?1+random.Next(2):random.Next(seas.Length)];var legacyLight=lights[random.Next(lights.Length)];
            var phases=lighting!=null&&lighting.cycleDayEveningNight?lighting.Build(SimulationFrames,captureEveryFrames):null;
            if(seaEvolution!=null&&seaEvolution.enabled) sea=seaEvolution.Evaluate(0,seed);
            return new DatasetSequencePlan{seed=seed,events=events.ToArray(),maxActive=MaxActive(events.ToArray(),durationSeconds),sea=sea,seaEvolution=seaEvolution,
                light=phases==null?legacyLight:phases[0].light,lightingPhases=phases};
        }
        public bool IntersectsObserverHull(DatasetEncounter encounter,float margin)
        {
            if(observerHullHalfExtentsM==Vector3.zero) return false;
            if(Mathf.Abs(observerTurnDeg)>.0001f) {
                // Conservative samples inflated by each interval's possible
                // translation/rotation: no gap between the sampled keep-outs.
                const float dt=.25f;float speedBound=encounter.velocity.magnitude+observerSpeedMps;
                float inflation=speedBound*dt*.5f+observerHullHalfExtentsM.magnitude*Mathf.Abs(observerTurnDeg)*Mathf.Deg2Rad/durationSeconds*dt*.5f;
                float curveBegin=Mathf.Max(0,encounter.startSeconds),curveEnd=Mathf.Min(durationSeconds,encounter.endSeconds);
                for(float t=curveBegin;t<curveEnd;t+=dt) {
                    float sample=Mathf.Min(curveEnd,t+dt*.5f);var curveRelative=encounter.Position(sample)-ObserverRoot(sample);
                    var curvePoint=new Vector3(Vector3.Dot(curveRelative,Bearing(ObserverHeading(sample)+90)),curveRelative.y,Vector3.Dot(curveRelative,Bearing(ObserverHeading(sample))));
                    var curveExtent=observerHullHalfExtentsM+Vector3.one*(margin+inflation);
                    if(Mathf.Abs(curvePoint.x)<=curveExtent.x&&Mathf.Abs(curvePoint.y)<=curveExtent.y&&Mathf.Abs(curvePoint.z)<=curveExtent.z) return true;
                }
                return false;
            }
            var forward=Bearing(routeHeadingDeg);var right=Bearing(routeHeadingDeg+90);
            float begin=Mathf.Max(0,encounter.startSeconds),end=Mathf.Min(durationSeconds,encounter.endSeconds);
            var relative=encounter.Position(0)-origin;var velocity=encounter.velocity-forward*observerSpeedMps;
            // Conservative swept box around the whole FREMM, not just a point
            // underneath its camera. Check the entire active trajectory.
            var p=new Vector3(Vector3.Dot(relative,right),relative.y,Vector3.Dot(relative,forward));
            var v=new Vector3(Vector3.Dot(velocity,right),velocity.y,Vector3.Dot(velocity,forward));
            var extent=observerHullHalfExtentsM+Vector3.one*margin;
            for(int axis=0;axis<3;axis++) {
                if(Mathf.Abs(v[axis])<1e-7f) {if(Mathf.Abs(p[axis])>extent[axis]) return false;}
                else {
                    float a=(-extent[axis]-p[axis])/v[axis],b=(extent[axis]-p[axis])/v[axis];
                    begin=Mathf.Max(begin,Mathf.Min(a,b));end=Mathf.Min(end,Mathf.Max(a,b));
                    if(begin>=end) return false;
                }
            }
            return begin<end;
        }
        public static bool TooClose(DatasetEncounter a,DatasetEncounter b,float separation,float duration)
        {
            float begin=Mathf.Max(0,Mathf.Max(a.startSeconds,b.startSeconds)),end=Mathf.Min(duration,Mathf.Min(a.endSeconds,b.endSeconds));
            if(begin>=end) return false;
            Vector3 relative=a.Position(begin)-b.Position(begin),v=a.velocity-b.velocity;
            float dt=v.sqrMagnitude<1e-8f?0:Mathf.Clamp(-Vector3.Dot(relative,v)/v.sqrMagnitude,0,end-begin);
            return (relative+v*dt).magnitude<separation;
        }
        public static int MaxActive(DatasetEncounter[] events,float duration)
        {
            int result=0;foreach(float t in events.Select(e=>Mathf.Max(0,e.startSeconds)).Where(t=>t<duration)) result=Math.Max(result,events.Count(e=>e.Active(t)));
            return result;
        }
        static float Between(System.Random random,Vector2 range) => range.x+(float)random.NextDouble()*(range.y-range.x);
        static bool Range(Vector2 value,float min,float max) => In(value.x,min,max)&&In(value.y,value.x,max);
        static bool In(float value,float min,float max) => Finite(value)&&value>=min&&value<=max;
        static bool Finite(float value) => !float.IsNaN(value)&&!float.IsInfinity(value);
    }
}
