using System;
using System.Collections.Generic;
using UnityEngine;

namespace Lotusim.EditorTools
{
    public static partial class AerialLibraryBuilder
    {
        static void BuildDrone(Transform parent)
        {
            var body=Loft("DroneShell",new[]{S(-.106f,.018f,.011f),S(-.087f,.046f,.023f,.005f),
                S(-.046f,.058f,.030f,.007f),S(.030f,.055f,.032f,.007f),S(.065f,.041f,.025f,.003f),
                S(.089f,.022f,.018f,-.002f),S(.096f,.005f,.009f,-.004f)},64,2,
                (z,a)=>Mathf.Sin(a)<-.18f?1:0);
            Add(parent,"Streamlined polymer shell",body,new[]{M("AirframeWhite"),M("BlackPlastic")});
            Box(parent,"Battery latch",new Vector3(0,.037f,-.052f),new Vector3(.021f,.004f,.025f),M("PolymerGrey"));
            for(int i=0;i<6;i++) Box(parent,"Cooling vent "+i,new Vector3(.036f,.018f,-.035f+i*.006f),new Vector3(.002f,.009f,.003f),M("BlackPlastic"));
            for(int side=-1;side<=1;side+=2) for(int fore=-1;fore<=1;fore+=2)
            {
                Vector3 motor=new Vector3(side*.139f,.004f,fore*.122f);
                Vector3 basePoint=new Vector3(side*.045f,-.006f,fore*.040f);
                Tube(parent,"Composite arm",basePoint,motor,.012f,M("RotorCarbon"),.72f);
                Tube(parent,"Motor can",motor-new Vector3(0,.012f,0),motor+new Vector3(0,.019f,0),.017f,M("DarkMetal"));
                Tube(parent,"Motor top ring",motor+new Vector3(0,.015f,0),motor+new Vector3(0,.020f,0),.018f,M("BrushedMetal"));
                Tube(parent,"Hub screw",motor+new Vector3(0,.019f,0),motor+new Vector3(0,.028f,0),.004f,M("DarkMetal"));
                var blades=Wing("DroneBlade",new[]{new Vector4(.007f,0,0,.011f),new Vector4(.025f,0,.002f,.016f),
                    new Vector4(.058f,-.001f,.007f,.013f),new Vector4(.073f,-.002f,.009f,.006f)},.09f,.025f,1,2,(span,a)=>span>.060f?1:0);
                for(int blade=0;blade<2;blade++) {
                    var rotor=Add(parent,"Two-blade propeller",blades,new[]{M("RotorCarbon"),M("SafetyYellow")},motor+new Vector3(0,.024f,0));
                    rotor.transform.localRotation=Quaternion.Euler(0,blade*180+side*fore*24,0);
                }
                Tube(parent,"Landing foot",motor-new Vector3(0,.015f,0),motor-new Vector3(0,.065f,0),.005f,M("BlackPlastic"));
                Ellipsoid(parent,"Foot cushion",motor-new Vector3(0,.065f,0),new Vector3(.008f,.003f,.011f),M("Rubber"));
                Ellipsoid(parent,"Navigation lens",motor+new Vector3(side*.017f,-.005f,0),new Vector3(.004f,.003f,.007f),M(fore>0?"NavRed":"NavGreen"));
            }
            var mount=new Vector3(0,-.037f,.067f);
            Tube(parent,"Camera suspension",new Vector3(0,-.021f,.055f),mount,.006f,M("BrushedMetal"));
            Ellipsoid(parent,"Gimbal ball",mount,new Vector3(.018f,.014f,.016f),M("BlackPlastic"));
            var camera=Box(parent,"Stabilized camera",new Vector3(0,-.058f,.085f),new Vector3(.033f,.024f,.025f),M("PolymerGrey"));
            camera.transform.localRotation=Quaternion.Euler(8,0,0);
            Tube(parent,"Camera lens barrel",new Vector3(0,-.058f,.096f),new Vector3(0,-.058f,.108f),.009f,M("DarkMetal"));
            Tube(parent,"Camera lens glass",new Vector3(0,-.058f,.108f),new Vector3(0,-.058f,.109f),.0078f,M("TintedGlazing"));
            for(int side=-1;side<=1;side+=2) Ellipsoid(parent,"Forward obstacle sensor",new Vector3(side*.028f,.006f,.073f),new Vector3(.006f,.005f,.005f),M("TintedGlazing"));
        }

        static void BuildHelicopter(Transform parent)
        {
            var cabin=Loft("HelicopterCabin",new[]{S(-1.95f,.12f,.16f,.1f),S(-1.65f,.34f,.43f,.05f),
                S(-1.2f,.66f,.66f),S(-.65f,.82f,.79f),S(-.12f,.84f,.84f,.02f),S(.3f,.81f,.84f,.02f),
                S(.75f,.73f,.79f,.01f),S(1.10f,.60f,.70f),S(1.43f,.38f,.51f,-.035f),S(1.64f,.035f,.21f,-.06f)},80,3,
                (z,a)=>{
                    float up=Mathf.Sin(a),side=Mathf.Abs(Mathf.Cos(a));
                    if((z>.45f && up>-.02f) || (z>-.6f && z<.28f && up>.02f && side>.5f)) return 1;
                    return up<-.25f?2:0;
                });
            Add(parent,"Curved glazed cabin",cabin,new[]{M("AirframeWhite"),M("TintedGlazing"),M("RescueOrange")});
            var boom=Loft("TaperedTailBoom",new[]{S(-5.05f,.06f,.08f,.57f),S(-4.7f,.095f,.115f,.55f),
                S(-3.9f,.135f,.16f,.48f),S(-2.8f,.195f,.205f,.35f),S(-1.62f,.27f,.275f,.18f)},48);
            Add(parent,"Tapered tail boom",boom,M("AirframeWhite"));
            Ellipsoid(parent,"Engine cowling",new Vector3(0,.82f,-.75f),new Vector3(.39f,.28f,.69f),M("RescueOrange"));
            for(int side=-1;side<=1;side+=2)
            {
                Tube(parent,"Turbine exhaust",new Vector3(side*.27f,.89f,-1.10f),new Vector3(side*.39f,.95f,-1.50f),.08f,M("DarkMetal"));
                Tube(parent,"Exhaust opening",new Vector3(side*.39f,.95f,-1.502f),new Vector3(side*.394f,.952f,-1.51f),.068f,M("BlackPlastic"));
                Tube(parent,"Door rear frame",new Vector3(side*.79f,-.22f,-.61f),new Vector3(side*.74f,.47f,-.61f),.017f,M("AirframeWhite"));
                Tube(parent,"Door front frame",new Vector3(side*.78f,-.25f,.36f),new Vector3(side*.66f,.57f,.36f),.017f,M("AirframeWhite"));
                Box(parent,"Door handle",new Vector3(side*.823f,-.13f,-.21f),new Vector3(.021f,.025f,.15f),M("DarkMetal"));
                var skid=new[]{new Vector3(side*.91f,-.94f,1.75f),new Vector3(side*.91f,-1.1f,1.52f),
                    new Vector3(side*.91f,-1.18f,1.24f),new Vector3(side*.91f,-1.18f,-1.45f),new Vector3(side*.91f,-1.12f,-1.65f)};
                for(int j=0;j<skid.Length-1;j++) Tube(parent,"Landing skid",skid[j],skid[j+1],.042f,M("DarkMetal"));
                for(int j=0;j<2;j++) {
                    float z=j==0?.76f:-.76f;
                    Tube(parent,"Landing support",new Vector3(side*.49f,-.52f,z),new Vector3(side*.91f,-1.15f,z),.036f,M("BrushedMetal"));
                    Box(parent,"Skid wear pad",new Vector3(side*.91f,-1.21f,z),new Vector3(.10f,.028f,.20f),M("Rubber"));
                }
                Ellipsoid(parent,"Navigation lamp",new Vector3(side*.85f,.10f,-.76f),new Vector3(.045f,.025f,.033f),M(side<0?"NavRed":"NavGreen"));
            }
            Tube(parent,"Main rotor mast",new Vector3(0,.89f,-.12f),new Vector3(0,1.46f,-.12f),.074f,M("BrushedMetal"));
            Ellipsoid(parent,"Rotor gearbox fairing",new Vector3(0,1.21f,-.12f),new Vector3(.20f,.13f,.20f),M("DarkMetal"));
            var rotorBlade=Wing("HelicopterMainBlade",new[]{new Vector4(.17f,0,0,.20f),new Vector4(.63f,0,0,.24f),
                new Vector4(3.8f,-.045f,-.08f,.22f),new Vector4(4.22f,-.062f,-.11f,.19f),new Vector4(4.55f,-.073f,-.16f,.155f)},.095f,.012f,1,2,
                (span,a)=>span>4.2f?1:0);
            for(int i=0;i<4;i++) {
                var blade=Add(parent,"Main rotor blade",rotorBlade,new[]{M("RotorCarbon"),M("SafetyYellow")},new Vector3(0,1.43f,-.12f));
                blade.transform.localRotation=Quaternion.Euler(0,i*90+18,0);
                Tube(parent,"Rotor pitch link",new Vector3(0,1.2f,-.12f),new Vector3(Mathf.Cos(i*Mathf.PI/2)*.2f,1.42f,-.12f+Mathf.Sin(i*Mathf.PI/2)*.2f),.009f,M("BrushedMetal"));
            }
            var fin=Wing("HelicopterTailFin",new[]{new Vector4(0,0,0,.58f),new Vector4(.65f,0,-.20f,.50f),new Vector4(1.20f,0,-.42f,.29f)},.08f,0);
            var finGo=Add(parent,"Vertical stabilizer",fin,M("RescueOrange"),new Vector3(0,.49f,-4.55f));finGo.transform.localRotation=Quaternion.Euler(0,0,90);
            for(int side=-1;side<=1;side+=2)
                Add(parent,"Tailplane",Wing("HelicopterTailplane"+side,new[]{new Vector4(.1f,0,0,.40f),new Vector4(.91f,.025f,-.08f,.28f)},.08f,0,side),M("AirframeWhite"),new Vector3(0,.42f,-3.95f));
            Tube(parent,"Tail rotor axle",new Vector3(-.05f,.56f,-4.83f),new Vector3(-.28f,.56f,-4.83f),.047f,M("DarkMetal"));
            var tailBlade=Wing("HelicopterTailBlade",new[]{new Vector4(.04f,0,0,.084f),new Vector4(.37f,0,-.025f,.075f),new Vector4(.51f,0,-.044f,.05f)},.10f,0,1,2,(span,a)=>span>.42f?1:0);
            for(int i=0;i<4;i++) {
                var blade=Add(parent,"Tail rotor blade",tailBlade,new[]{M("RotorCarbon"),M("SafetyYellow")},new Vector3(-.29f,.56f,-4.83f));
                blade.transform.localRotation=Quaternion.AngleAxis(i*90+20,Vector3.right)*Quaternion.Euler(0,0,90);
            }
            Tube(parent,"Telemetry aerial",new Vector3(0,.66f,-2.0f),new Vector3(0,1.12f,-2.09f),.006f,M("DarkMetal"));
        }

        static void BuildAirplane(Transform parent)
        {
            var fuselage=Loft("AirplaneFuselage",new[]{S(-3.55f,.035f,.08f,.24f),S(-3.18f,.11f,.17f,.20f),S(-2.5f,.21f,.26f,.10f),
                S(-1.8f,.36f,.40f,.04f),S(-.9f,.51f,.55f),S(-.3f,.55f,.63f),S(.12f,.55f,.65f),S(.53f,.53f,.67f),
                S(1.05f,.48f,.64f),S(1.60f,.39f,.54f),S(2.00f,.34f,.31f,-.08f),S(2.5f,.36f,.32f,-.08f),
                S(3.08f,.31f,.27f,-.08f),S(3.30f,.21f,.19f,-.08f)},80,3,
                (z,a)=>{
                    float up=Mathf.Sin(a),side=Mathf.Abs(Mathf.Cos(a));
                    if((z>.70f && z<1.85f && up>.12f) || (z>-.16f && z<.62f && up>.02f && side>.63f)) return 1;
                    return up>-.38f && up<-.10f && z>-2.9f && z<2.35f?2:0;
                });
            Add(parent,"Fuselage and cabin glazing",fuselage,new[]{M("AirframeWhite"),M("TintedGlazing"),M("AircraftBlue")});
            for(int side=-1;side<=1;side+=2)
            {
                var stations=new[]{new Vector4(.36f,.61f,.03f,1.55f),new Vector4(1.7f,.65f,-.05f,1.44f),
                    new Vector4(3.7f,.74f,-.14f,1.23f),new Vector4(5.1f,.83f,-.28f,.93f),new Vector4(5.40f,.84f,-.34f,.72f)};
                Add(parent,"Main wing",Wing("AirplaneWing"+side,stations,.125f,.024f,side,2,(span,a)=>span>5.0f?1:0),new[]{M("AirframeWhite"),M("AircraftBlue")});
                Tube(parent,"Lift strut",new Vector3(side*.40f,-.32f,-.12f),new Vector3(side*2.38f,.66f,.11f),.037f,M("BrushedMetal"),.47f);
                Tube(parent,"Aileron hinge",new Vector3(side*2.35f,.63f,-.78f),new Vector3(side*5.08f,.81f,-.76f),.005f,M("PolymerGrey"));
                Add(parent,"Horizontal stabilizer",Wing("AirplaneTailplane"+side,new[]{new Vector4(.09f,0,0,.87f),new Vector4(1.3f,.045f,-.19f,.66f),new Vector4(1.72f,.052f,-.32f,.36f)},.10f,0,side),M("AirframeWhite"),new Vector3(0,.20f,-2.88f));
                Tube(parent,"Main landing strut",new Vector3(side*.39f,-.28f,.22f),new Vector3(side*.93f,-.83f,.10f),.041f,M("AirframeWhite"),.47f);
                Wheel(parent,"Main tyre",new Vector3(side*.98f,-.87f,.10f),.185f,.060f);
                Ellipsoid(parent,"Wingtip navigation light",new Vector3(side*5.405f,.865f,-.12f),new Vector3(.026f,.018f,.060f),M(side<0?"NavRed":"NavGreen"));
                Tube(parent,"Cabin door pillar",new Vector3(side*.535f,.08f,.66f),new Vector3(side*.438f,.52f,.72f),.015f,M("AirframeWhite"));
                Box(parent,"Door handle",new Vector3(side*.553f,.03f,.24f),new Vector3(.013f,.026f,.13f),M("BrushedMetal"));
            }
            var vertical=Add(parent,"Vertical fin",Wing("AirplaneVerticalFin",new[]{new Vector4(0,0,0,1.02f),new Vector4(.65f,0,-.31f,.87f),new Vector4(1.31f,0,-.72f,.41f)},.095f,0,1,2,(span,a)=>span>.91f?1:0),
                new[]{M("AirframeWhite"),M("AircraftBlue")},new Vector3(0,.25f,-2.86f));
            vertical.transform.localRotation=Quaternion.Euler(0,0,90);
            Add(parent,"Propeller spinner",Loft("AirplaneSpinner",new[]{S(3.25f,.22f,.22f,-.08f),S(3.49f,.18f,.18f,-.08f),S(3.66f,.025f,.025f,-.08f)},48),M("AircraftBlue"));
            var prop=Wing("AirplanePropeller",new[]{new Vector4(.09f,0,0,.11f),new Vector4(.28f,0,.025f,.17f),new Vector4(.68f,-.013f,.09f,.13f),new Vector4(.86f,-.022f,.12f,.072f)},.105f,.015f,1,2,(span,a)=>span>.73f?1:0);
            for(int blade=0;blade<2;blade++) {
                var go=Add(parent,"Two-blade propeller",prop,new[]{M("RotorCarbon"),M("SafetyYellow")},new Vector3(0,-.08f,3.35f));
                go.transform.localRotation=Quaternion.AngleAxis(25+blade*180,Vector3.forward)*Quaternion.Euler(90,0,0);
            }
            Tube(parent,"Nose landing strut",new Vector3(0,-.34f,2.15f),new Vector3(0,-.96f,2.15f),.030f,M("BrushedMetal"));
            Wheel(parent,"Nose tyre",new Vector3(0,-1.01f,2.15f),.122f,.046f);
            for(int side=-1;side<=1;side+=2) {
                Ellipsoid(parent,"Engine air inlet",new Vector3(side*.22f,-.09f,3.08f),new Vector3(.066f,.039f,.052f),M("BlackPlastic"));
                for(int i=0;i<7;i++) Ellipsoid(parent,"Cowling fastener",new Vector3(side*.336f,-.05f,2.10f+i*.13f),new Vector3(.006f,.006f,.006f),M("BrushedMetal"));
            }
            Tube(parent,"VHF antenna",new Vector3(0,.67f,-.25f),new Vector3(0,1.03f,-.33f),.007f,M("DarkMetal"));
        }

        static void Wheel(Transform parent,string name,Vector3 position,float major,float minor)
        {
            string key="Tyre_"+major.ToString("F3",System.Globalization.CultureInfo.InvariantCulture).Replace('.','_');
            var tyre=Add(parent,name,RingMesh(key,major,minor),M("Rubber"),position);
            tyre.transform.localRotation=Quaternion.FromToRotation(Vector3.up,Vector3.right);
            Tube(parent,"Wheel rim",position-new Vector3(minor*.65f,0,0),position+new Vector3(minor*.65f,0,0),major*.64f,M("BrushedMetal"));
            Tube(parent,"Axle cap",position-new Vector3(minor,0,0),position+new Vector3(minor,0,0),major*.19f,M("DarkMetal"));
        }

        static void BuildSeagull(Transform parent)
        {
            Add(parent,"Streamlined feathered body",Loft("GullBody",new[]{S(-.295f,.021f,.027f),S(-.245f,.068f,.058f),
                S(-.15f,.098f,.078f),S(-.02f,.105f,.083f),S(.105f,.084f,.080f,.015f),S(.18f,.047f,.049f,.053f),S(.235f,.028f,.034f,.067f)},64),M("BirdWhite"));
            Ellipsoid(parent,"Head",new Vector3(0,.075f,.255f),new Vector3(.052f,.054f,.062f),M("BirdWhite"));
            var upper=Loft("GullUpperBill",new[]{S(.295f,.015f,.012f,.057f),S(.34f,.014f,.012f,.057f),S(.389f,.005f,.007f,.047f),S(.403f,.001f,.003f,.041f)},32);
            Add(parent,"Hooked yellow upper bill",upper,M("BirdBill"));
            Add(parent,"Lower bill",Loft("GullLowerBill",new[]{S(.30f,.012f,.004f,.042f),S(.36f,.009f,.004f,.041f),S(.393f,.001f,.001f,.039f)},24),M("BirdBill"));
            Ellipsoid(parent,"Bill reference patch",new Vector3(.007f,.040f,.361f),new Vector3(.0015f,.005f,.009f),M("BillMark"));
            for(int side=-1;side<=1;side+=2)
            {
                Ellipsoid(parent,"Dark eye",new Vector3(side*.048f,.085f,.280f),new Vector3(.0043f,.0043f,.0043f),M("BirdEye"));
                var ring=Add(parent,"Orbital ring",RingMesh("GullEyeRing",.0052f,.00075f),M("BirdBill"),new Vector3(side*.050f,.085f,.280f));
                ring.transform.localRotation=Quaternion.FromToRotation(Vector3.up,Vector3.right);
                var stations=new[]{new Vector4(.060f,.033f,.01f,.22f),new Vector4(.20f,.047f,-.006f,.27f),
                    new Vector4(.37f,.043f,-.062f,.235f),new Vector4(.51f,.026f,-.17f,.18f),new Vector4(.625f,-.001f,-.29f,.075f)};
                Add(parent,"Spread wing",Wing("GullWing"+side,stations,.065f,.045f,side,3,(span,a)=>
                    a>Mathf.PI?0:span>.525f?2:1),new[]{M("BirdWhite"),M("BirdGrey"),M("BirdBlack")});
                // Individually shaped, overlapping remiges give the trailing edge and tips an organic silhouette.
                for(int i=0;i<12;i++) {
                    float t=i/11f;
                    Vector3 start=new Vector3(side*(.14f+t*.39f),.050f-t*.018f,-.045f-t*.15f);
                    Vector3 end=new Vector3(side*(.19f+t*.465f),.017f-t*.04f,-.22f-t*.145f);
                    Feather(parent,"Flight feather",start,end,.014f+(1-t)*.004f,i>8?M("BirdBlack"):M("BirdGrey"));
                    if(i>8) Ellipsoid(parent,"Primary white spot",Vector3.Lerp(start,end,.88f)+new Vector3(0,.0017f,0),new Vector3(.005f,.0018f,.012f),M("BirdWhite"));
                }
                for(int i=0;i<10;i++) {
                    float t=i/9f;
                    Feather(parent,"Upper covert",new Vector3(side*(.10f+t*.37f),.064f,-.007f-t*.075f),
                        new Vector3(side*(.15f+t*.36f),.044f,-.104f-t*.087f),.016f,M("BirdGrey"));
                }
                Tube(parent,"Folded leg",new Vector3(side*.027f,-.051f,-.13f),new Vector3(side*.032f,-.07f,-.23f),.003f,M("BirdBill"));
                Tube(parent,"Folded tarsus",new Vector3(side*.032f,-.07f,-.23f),new Vector3(side*.039f,-.052f,-.286f),.0025f,M("BirdBill"));
                for(int toe=-1;toe<=1;toe++) Tube(parent,"Folded toe",new Vector3(side*.039f,-.052f,-.282f),new Vector3(side*.039f+toe*.008f,-.05f,-.312f),.0017f,M("BirdBill"));
            }
            for(int i=0;i<9;i++) {
                float a=(i-4)*.14f;
                Feather(parent,"Tail feather",new Vector3((i-4)*.01f,-.007f,-.225f),
                    new Vector3(Mathf.Sin(a)*.16f,-.028f,-.450f+Mathf.Abs(a)*.020f),.020f,M("BirdWhite"));
            }
        }

        static void Feather(Transform parent,string name,Vector3 start,Vector3 end,float width,Material material)
        {
            float length=(end-start).magnitude;
            // Quill and vanes form a real, closed mesh rather than a transparent billboard.
            var mesh=Loft("Feather_"+width.ToString("F6",System.Globalization.CultureInfo.InvariantCulture).Replace('.','_')+"_"+
                length.ToString("F6",System.Globalization.CultureInfo.InvariantCulture).Replace('.','_'),new[]{
                S(0,width*.12f,.0010f),S(length*.20f,width*.80f,.0016f),S(length*.55f,width,.0017f),
                S(length*.84f,width*.66f,.0012f),S(length,width*.035f,.0003f)},20);
            var go=Add(parent,name,mesh,material,start);go.transform.localRotation=Quaternion.FromToRotation(Vector3.forward,end-start);
        }
    }
}
