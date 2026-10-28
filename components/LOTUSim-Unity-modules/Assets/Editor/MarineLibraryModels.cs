using System;
using Lotusim.Dataset;
using UnityEngine;

namespace Lotusim.EditorTools
{
    public static partial class MarineLibraryBuilder
    {
        static Vector3 P(float x,float y,float z=0)=>new Vector3(x,y,z);
        static void Hull(Geometry g,MarineVesselParameters p,float freeboard,int color,int deck=Deck)=>g.Hull(p.lengthM,p.beamM,p.draftM,freeboard,color,Antifoul,deck,Black);
        static void Rails(Geometry g,MarineVesselParameters p,float deck,float height=.9f,int count=28,bool cable=false)
        {
            float radius=Mathf.Clamp(p.beamM*.003f,.012f,.035f);
            for(int side=-1;side<=1;side+=2) {
                Vector3 previous=Vector3.zero,previousMid=Vector3.zero;
                for(int i=0;i<=count;i++) {
                    float t=.02f+i/(float)count*.94f,x=(t-.5f)*p.lengthM,z=side*p.beamM*.48f*HullWidth(t),y=deck*(1+.35f*Mathf.Pow(t,5));
                    Vector3 foot=P(x,y,z),top=foot+Vector3.up*height,mid=foot+Vector3.up*(height*.47f);
                    g.Tube(foot,top,radius,Steel);if(i>0) {g.Tube(previous,top,radius*(cable?.4f:1),Steel);g.Tube(previousMid,mid,radius*(cable?.35f:.65f),Steel);}
                    previous=top;previousMid=mid;
                }
            }
        }
        static void Cabin(Geometry g,Vector3 center,Vector3 size,int material=White,int windows=5)
        {
            g.Box(center,size,material,Mathf.Min(size.x,size.z)*.12f);g.Box(center+Vector3.up*(size.y/2+.06f),new Vector3(size.x+.16f,.13f,size.z+.16f),material,.15f);
            float y=center.y+size.y*.20f,h=size.y*.30f;
            for(int side=-1;side<=1;side+=2) for(int j=0;j<windows;j++) {
                float x=center.x+(j-(windows-1)/2f)*size.x/(windows+.7f);float w=size.x/(windows+1.4f)*.77f;
                g.Box(P(x,y,center.z+side*(size.z/2+.013f)),P(w+.06f,h+.06f,.035f),DarkMetal,.025f);
                g.Box(P(x,y,center.z+side*(size.z/2+.035f)),P(w,h,.016f),Glass,.015f);
            }
            for(int j=0;j<3;j++) {
                float z=center.z+(j-1)*size.z*.26f;
                g.Box(P(center.x+size.x/2+.015f,y,z),P(.032f,h+.05f,size.z*.23f),DarkMetal,.008f);
                g.Box(P(center.x+size.x/2+.035f,y,z),P(.018f,h,size.z*.21f),Glass,.006f);
                g.Tube(P(center.x+size.x/2+.05f,y-h*.3f,z-.06f),P(center.x+size.x/2+.05f,y+h*.2f,z+.04f),.012f,Black);
            }
            // Side access door, handle, hinges and ventilation louvres.
            g.Box(center+P(-size.x*.31f,-size.y*.10f,size.z/2+.025f),P(size.x*.14f,size.y*.65f,.025f),DarkMetal,.025f);
            g.Box(center+P(-size.x*.31f,-size.y*.10f,size.z/2+.045f),P(size.x*.125f,size.y*.61f,.02f),material,.02f);
            g.Tube(center+P(-size.x*.27f,-size.y*.11f,size.z/2+.10f),center+P(-size.x*.27f+.1f,-size.y*.11f,size.z/2+.10f),.016f,Steel);
            for(int i=0;i<7;i++) g.Box(center+P(-size.x*.35f,-size.y*.25f+i*.045f,-size.z/2-.025f),P(size.x*.16f,.018f,.04f),DarkMetal);
        }
        static void Mast(Geometry g,Vector3 foot,float height,float spread=1.2f)
        {
            g.Tube(foot,foot+Vector3.up*height,.055f,Steel,.025f,16);
            g.Tube(foot+P(0,height*.62f,-spread/2),foot+P(0,height*.62f,spread/2),.035f,Steel);
            g.Box(foot+P(0,height*.72f),P(.28f,.20f,spread*1.15f),White,.06f);
            g.Tube(foot+P(-.15f,height*.68f),foot+P(-.15f,height+.65f),.012f,DarkMetal);
            g.Ellipsoid(foot+P(0,height),P(.07f,.10f,.07f),NavWhite,16,10);
            g.Tube(foot+P(.2f,height*.2f),foot+P(.24f,height*.9f),.009f,DarkMetal);
        }
        static void Cleat(Geometry g,Vector3 p,float size=.28f)
        {
            g.Box(p,P(size*.65f,.035f,size*.45f),Steel,.02f);g.Tube(p,p+P(0,.10f),size*.09f,Steel);
            g.Tube(p+P(-size/2,.11f),p+P(size/2,.11f),size*.07f,Steel);
        }
        static void Lifering(Geometry g,Vector3 p,float radius=.3f)
        {
            g.Ring(p,Vector3.forward,radius,radius*.18f,Orange,24);g.Ring(p+P(0,0,.02f),Vector3.forward,radius*1.12f,radius*.02f,RopeMat,24);
            for(int i=0;i<4;i++) {float a=i*Mathf.PI/2;g.Ellipsoid(p+P(Mathf.Cos(a)*radius,Mathf.Sin(a)*radius,.01f),P(radius*.15f,radius*.15f,radius*.19f),White,12,8);}
        }
        static void Navigation(Geometry g,float x,float y,float halfBeam)
        {
            for(int side=-1;side<=1;side+=2) {
                g.Box(P(x,y,side*halfBeam),P(.15f,.09f,.10f),Black,.02f);
                g.Ellipsoid(P(x+.025f,y+.07f,side*halfBeam),P(.055f,.06f,.055f),side>0?NavRed:NavGreen,16,10);
            }
        }
        static void Anchor(Geometry g,Vector3 p,float scale=1)
        {
            g.Tube(p,p+P(0,-scale),.045f*scale,Steel);g.Tube(p+P(-.38f*scale,-.7f*scale),p+P(.38f*scale,-.7f*scale),.035f*scale,Steel);
            g.Tube(p+P(-.38f*scale,-.7f*scale),p+P(-.48f*scale,-.40f*scale),.045f*scale,Steel,.012f*scale);
            g.Tube(p+P(.38f*scale,-.7f*scale),p+P(.48f*scale,-.40f*scale),.045f*scale,Steel,.012f*scale);
            g.Ring(p,Vector3.forward,.08f*scale,.02f*scale,Steel,16);
        }
        static void Fenders(Geometry g,float length,float beam,float deck,int count=4)
        {
            for(int side=-1;side<=1;side+=2) for(int i=0;i<count;i++) {
                var point=P(-length*.3f+i*length*.56f/(count-1),deck-.35f,side*(beam/2+.09f));
                g.Tube(point+P(0,-.17f),point+P(0,.17f),.11f,White,.11f,20);g.Ellipsoid(point+P(0,-.17f),P(.11f,.10f,.11f),White,16,8);
                g.Rope(point+P(0,.17f),point+P(0,.75f,-side*.14f),.03f,.009f,RopeMat,6);
            }
        }
        static void Trawler(Geometry g,MarineVesselParameters p)
        {
            const float deck=1.8f;Hull(g,p,deck,Blue);Rails(g,p,deck,1.05f,32);
            Cabin(g,P(3.5f,3.15f),P(6.2f,2.5f,5.2f),White,5);Cabin(g,P(4.2f,5.20f),P(4.9f,1.6f,4.7f),White,5);Mast(g,P(4.5f,6.15f),3.0f,2.6f);
            for(int side=-1;side<=1;side+=2) {
                g.Tube(P(-7,deck,side*2.6f),P(-7,7.0f,side*2.6f),.14f,Orange,around:20);
                g.Tube(P(-8.8f,deck,side*2.7f),P(-7,6.3f,side*2.6f),.095f,Orange);
                g.Tube(P(-7,7,side*2.6f),P(-7,7,0),.14f,Orange);
                g.Tube(P(-4,deck+.55f,side*1.2f),P(-4,deck+.55f,side*2.2f),.48f,DarkMetal,around:28);
                for(int r=0;r<11;r++) g.Ring(P(-4,deck+.55f,side*(1.22f+r*.085f)),Vector3.forward,.45f,.024f,RopeMat,24);
                g.Rope(P(-4,deck+.9f,side*1.7f),P(-7,6.9f,side*2.1f),.15f,.025f,RopeMat);
                g.Rope(P(-7,6.9f,side*2.1f),P(-11,2.4f,side*2.7f),.2f,.025f,RopeMat);
                for(int j=0;j<5;j++) g.Box(P(-1.5f+j*.65f,deck+.23f,side*2.15f),P(.55f,.45f,.85f),j%2==0?CargoBlue:CargoGrey,.025f);
                Lifering(g,P(2.5f,3.35f,side*2.68f),.32f);
                Cleat(g,P(9,deck*1.2f,side*1.45f),.45f);
                // Rubber tyres and hanging ropes, not flat painted circles.
                for(int i=0;i<4;i++) {var at=P(-5+i*3.0f,.65f,side*3.48f);g.Ring(at,Vector3.forward,.38f,.11f,Rubber,24);g.Rope(at+P(0,.3f),at+P(.13f,1.5f,-side*.12f),.1f,.018f,RopeMat);}
            }
            g.Ellipsoid(P(-8.3f,deck+.45f),P(1.7f,.42f,1.35f),Net);
            for(int i=0;i<14;i++) g.Rope(P(-9.7f+i*.22f,deck+.25f,-1.3f),P(-9.7f+i*.22f,deck+.25f,1.3f),-.35f,.018f,RopeMat);
            for(int i=0;i<10;i++) g.Rope(P(-9.7f,deck+.2f,-1.15f+i*.25f),P(-6.8f,deck+.2f,-1.15f+i*.25f),-.28f,.018f,Net);
            g.Box(P(-10.9f,2.25f),P(.45f,.5f,4.2f),Steel,.06f);g.Tube(P(-10.9f,2.55f,-2),P(-10.9f,2.55f,2),.18f,Steel,around:24);
            g.Tube(P(1.7f,5.8f,-1.4f),P(1.7f,7.2f,-1.4f),.18f,DarkMetal);g.Tube(P(1.7f,7.2f,-1.4f),P(1.4f,7.25f,-1.4f),.18f,DarkMetal);
            Navigation(g,4.8f,6.1f,2.5f);Anchor(g,P(10.0f,.8f,1.2f));
        }
        static void Container(Geometry g,Vector3 p,int color)
        {
            g.Box(p,P(12.05f,2.50f,2.40f),color,.08f);
            for(int side=-1;side<=1;side+=2) {
                for(int r=0;r<18;r++) g.Box(p+P(-5.65f+r*.66f,0,side*1.215f),P(.07f,2.28f,.07f),color,.018f);
                for(int end=-1;end<=1;end+=2) g.Box(p+P(end*5.98f,0,side*1.19f),P(.12f,2.58f,.13f),color,.02f);
                for(int edge=-1;edge<=1;edge+=2) g.Box(p+P(0,edge*1.23f,side*1.20f),P(12.1f,.12f,.12f),color,.02f);
            }
            for(int panel=-1;panel<=1;panel+=2) {
                g.Box(p+P(-6.04f,0,panel*.59f),P(.035f,2.28f,1.13f),color,.015f);
                for(int bar=-1;bar<=1;bar+=2) {
                    float z=panel*.59f+bar*.32f;g.Tube(p+P(-6.08f,-1.12f,z),p+P(-6.08f,1.12f,z),.021f,Steel,around:8);
                    g.Box(p+P(-6.12f,-.4f,z),P(.06f,.06f,.20f),Steel,.008f);
                }
            }
        }
        static void ContainerShip(Geometry g,MarineVesselParameters p)
        {
            const float deck=4.8f;Hull(g,p,deck,GreyHull);Rails(g,p,deck,1.1f,64);
            for(int bay=0;bay<9;bay++) for(int column=0;column<8;column++) {
                int tiers=bay==8?2:bay==7&&column%3==0?3:4;
                for(int tier=0;tier<tiers;tier++) Container(g,P(-45+bay*12.35f,deck+1.30f+tier*2.62f,(column-3.5f)*2.52f),CargoRed+(bay*7+column*3+tier*11)%5);
            }
            for(int level=0;level<5;level++) Cabin(g,P(-73,deck+1.4f+level*2.75f),P(17,2.60f,22-level*.30f),White,11);
            Cabin(g,P(-71.3f,20.4f),P(19.5f,2.50f,26),White,12);Mast(g,P(-72.5f,21.85f),6.2f,5);
            g.Box(P(-82,19,-5.1f),P(5.2f,9.2f,7),Blue,.8f);
            for(int i=0;i<3;i++) g.Tube(P(-82+i*1.25f,23.3f,-5.1f),P(-82+i*1.25f,25.3f,-5.1f),.40f,Black,around:20);
            for(int side=-1;side<=1;side+=2) {
                for(int x=0;x<4;x++) Cleat(g,P(69+x*4.2f,5.6f,side*(8.5f-x)),1.2f);
                Anchor(g,P(81.5f,3.0f,side*5.2f),2.8f);
                var boat=P(-78,13,side*12.1f);g.Ellipsoid(boat,P(3.8f,1.0f,1.15f),Orange);g.Ellipsoid(boat+P(0,.65f),P(2.6f,.7f,.8f),White);
                for(int j=0;j<2;j++) g.Tube(boat+P((j-.5f)*4,-1.8f,side*.8f),boat+P((j-.5f)*4,2,side*.5f),.12f,Steel);
            }
            Navigation(g,-63,21.7f,13.5f);
            for(int i=0;i<12;i++) g.Box(P(-88+i*.32f,6,.4f),P(.10f,.08f,8),Yellow);
        }
        static void Yacht(Geometry g,MarineVesselParameters p)
        {
            const float deck=1.1f;Hull(g,p,deck,White,Teak);Rails(g,p,deck,.70f,26);
            // The glazing is the actual tapered coachroof skin, not a sloping
            // pane hidden inside a solid cabin box.
            g.Box(P(-.1f,1.38f),P(6.2f,.55f,3.30f),White,.6f);g.Box(P(-.35f,2.94f),P(7.0f,.20f,3.55f),White,.65f);
            for(int side=-1;side<=1;side+=2) {
                g.Quad(P(3.05f,1.55f,side*1.67f),P(2.30f,2.85f,side*1.48f),P(-2.4f,2.85f,side*1.48f),P(-3.2f,1.55f,side*1.67f),Glass,Vector3.forward*side);
                for(int j=0;j<5;j++) {float x=-2.3f+j*1.05f;g.Tube(P(x,1.55f,side*1.69f),P(x+.25f,2.85f,side*1.50f),.028f,Steel);}
                for(int i=0;i<4;i++) g.Ellipsoid(P(-3+i*1.5f,.45f,side*p.beamM*.48f),P(.30f,.13f,.025f),Glass,24,12);
                Cleat(g,P(4.9f,1.4f,side*.8f));Lifering(g,P(-2.8f,2.15f,side*1.75f),.24f);
            }
            g.Quad(P(3.05f,1.55f,-1.67f),P(3.05f,1.55f,1.67f),P(2.30f,2.85f,1.48f),P(2.30f,2.85f,-1.48f),Glass,Vector3.right);
            g.Quad(P(-3.2f,1.55f,1.67f),P(-3.2f,1.55f,-1.67f),P(-2.4f,2.85f,-1.48f),P(-2.4f,2.85f,1.48f),Glass,Vector3.left);
            g.Box(P(3.9f,1.48f),P(2.3f,.24f,2.15f),Cream,.30f);g.Box(P(-4.6f,1.40f),P(2.3f,.44f,2.8f),Cream,.2f);
            for(int i=0;i<7;i++) g.Box(P(-4.6f,1.63f,-1.1f+i*.36f),P(2.0f,.012f,.01f),Teak);
            g.Box(P(-7.0f,.65f),P(1.15f,.18f,3.2f),Teak,.3f);
            for(int i=0;i<3;i++) g.Box(P(-6.25f+i*.25f,.85f+i*.14f),P(.30f,.12f,2.1f),Teak,.05f);
            g.Box(P(-.6f,3.16f),P(3.7f,.30f,2.7f),White,.4f);
            for(int side=-1;side<=1;side+=2) g.Tube(P(-1.7f,3.5f,side*1.2f),P(-1.4f,4.5f,side*1.05f),.07f,White);
            g.Box(P(-1.4f,4.5f),P(.7f,.18f,2.4f),White,.15f);Mast(g,P(-1.4f,4.6f),1.0f,1.3f);
            Navigation(g,1.9f,3.2f,1.72f);Fenders(g,12,4.3f,1.3f,4);Anchor(g,P(6.2f,.7f),.55f);
        }
        static void Outboard(Geometry g,Vector3 p,float scale)
        {
            g.Ellipsoid(p+P(-.2f,.1f)*scale,P(.35f,.47f,.23f)*scale,DarkMetal);g.Box(p+P(.13f,-.12f)*scale,P(.20f,.65f,.28f)*scale,Steel,.025f);
            g.Tube(p+P(-.22f,-.2f)*scale,p+P(-.23f,-1)*scale,.085f*scale,DarkMetal,.06f*scale);
            g.Tube(p+P(-.43f,-.96f)*scale,p+P(-.1f,-.96f)*scale,.11f*scale,Steel,.055f*scale,20);
            for(int blade=0;blade<3;blade++) {float a=blade*2*Mathf.PI/3;g.Ellipsoid(p+P(-.43f,-.96f+Mathf.Cos(a)*.14f,Mathf.Sin(a)*.14f)*scale,P(.035f,.09f,.09f)*scale,Steel,16,10);}
        }
        static void Speedboat(Geometry g,MarineVesselParameters p)
        {
            const float deck=.62f;Hull(g,p,deck,Blue,White);Rails(g,p,deck,.43f,20);
            g.Box(P(-.6f,.65f),P(3.4f,.04f,1.9f),Deck,.15f);
            for(int side=-1;side<=1;side+=2) {
                g.Box(P(.0f,.94f,side*.55f),P(.70f,.25f,.65f),Cream,.12f);g.Box(P(-.3f,1.20f,side*.55f),P(.17f,.6f,.65f),Cream,.08f);
                g.Tube(P(-.6f,.75f,side*.87f),P(-.6f,1.85f,side*.87f),.022f,Steel);
                g.Tube(P(-1.7f,.75f,side*.87f),P(-1.7f,1.85f,side*.87f),.022f,Steel);
                g.Quad(P(1.1f,.74f,side*.95f),P(.82f,1.37f,side*.82f),P(.10f,1.37f,side*.82f),P(.10f,.74f,side*.95f),Glass,Vector3.forward*side);
                Cleat(g,P(2.5f,.94f,side*.45f),.18f);
            }
            g.Quad(P(1.1f,.74f,-.95f),P(1.1f,.74f,.95f),P(.82f,1.37f,.82f),P(.82f,1.37f,-.82f),Glass,Vector3.right);
            g.Box(P(-1.15f,1.85f),P(1.7f,.045f,1.95f),Canvas,.10f);g.Box(P(-2.05f,.94f),P(.8f,.28f,1.8f),Cream,.1f);
            g.Box(P(.6f,.95f,-.45f),P(.6f,.4f,.55f),White,.05f);g.Ring(P(.38f,1.20f,-.45f),Vector3.right,.17f,.022f,Black,24);
            Outboard(g,P(-3.2f,.53f),1);Navigation(g,1.1f,.9f,1.05f);Anchor(g,P(2.85f,.5f),.28f);
        }
        static void Jetski(Geometry g,MarineVesselParameters p)
        {
            Hull(g,p,.24f,White,Black);g.Ellipsoid(P(.08f,.29f),P(1.35f,.28f,.53f),Orange,40,20);
            g.Ellipsoid(P(-.38f,.56f),P(.78f,.20f,.29f),Black,36,18);
            for(int side=-1;side<=1;side+=2) {
                g.Box(P(-.45f,.24f,side*.47f),P(1.45f,.04f,.21f),Rubber,.08f);
                for(int rib=0;rib<12;rib++) g.Box(P(-1.05f+rib*.11f,.267f,side*.47f),P(.025f,.012f,.16f),DarkMetal);
                g.Tube(P(.6f,.57f),P(.62f,.84f,side*.36f),.026f,Steel);g.Tube(P(.62f,.84f,side*.24f),P(.62f,.84f,side*.39f),.034f,Rubber);
                g.Ellipsoid(P(.69f,.69f,side*.28f),P(.12f,.04f,.09f),Glass,16,10);
            }
            g.Tube(P(.5f,.38f),P(.62f,.80f),.075f,Black,.045f);g.Box(P(.60f,.78f),P(.17f,.03f,.20f),Glass,.03f);
            g.Tube(P(-1.40f,-.04f),P(-1.62f,-.04f),.11f,DarkMetal,.09f,24);g.Ring(P(-1.62f,-.04f),Vector3.right,.10f,.014f,Steel,24);
            g.Rope(P(.55f,.77f,-.15f),P(.10f,.5f,-.30f),.08f,.006f,Orange,12);g.Tube(P(-1.2f,.50f,-.18f),P(-1.2f,.50f,.18f),.026f,Steel);
        }
        static void Ferry(Geometry g,MarineVesselParameters p)
        {
            const float deck=2.3f;Hull(g,p,deck,White);Rails(g,p,deck,1.05f,48);
            Cabin(g,P(-1,4.0f),P(58,3.2f,14.5f),White,25);Cabin(g,P(-2,7.0f),P(54,2.7f,14.2f),White,25);
            Cabin(g,P(23,9.4f),P(10,2.5f,15.6f),White,7);g.Box(P(-6,9.0f),P(35,.25f,12),Deck,.6f);
            for(int side=-1;side<=1;side+=2) {
                g.Box(P(-.5f,3,side*7.28f),P(57,.22f,.08f),Blue);
                for(int i=0;i<3;i++) {
                    var at=P(-19+i*13,9.15f,side*6.6f);g.Ellipsoid(at,P(2.7f,.72f,1.0f),Orange);g.Ellipsoid(at+P(0,.43f),P(1.75f,.52f,.70f),White);
                    for(int j=-1;j<=1;j+=2) {g.Tube(at+P(j*1.8f,-.8f,side*.6f),at+P(j*1.8f,1.5f,side*.4f),.08f,Steel);g.Rope(at+P(j*1.8f,1.4f),at+P(j*1.8f,.6f),0,.013f,RopeMat);}
                }
                for(int i=0;i<6;i++) {
                    var at=P(-25+i*5,9.15f,side*4.8f);g.Tube(at+P(0,0,-.43f),at+P(0,0,.43f),.35f,White,around:24);g.Ring(at+P(0,0,.25f),Vector3.forward,.36f,.026f,DarkMetal,20);
                }
                Lifering(g,P(20,6.8f,side*7.25f),.40f);Anchor(g,P(31,1.7f,side*3),1.4f);
            }
            g.Box(P(-10,10.8f),P(5.3f,4.2f,5),Blue,.65f);for(int i=0;i<3;i++) g.Tube(P(-11.4f+i*1.4f,12.6f),P(-11.4f+i*1.4f,14.2f),.35f,Black,around:20);
            for(int i=0;i<4;i++) {g.Box(P(-22+i*7,9.4f),P(4,1.05f,3),GreyHull,.15f);for(int j=0;j<8;j++) g.Box(P(-23.5f+i*7+j*.4f,9.95f),P(.10f,.035f,2.8f),DarkMetal);}
            g.Box(P(-35.5f,3.25f),P(.10f,3.2f,7),Black,.05f);g.Box(P(-37,1.8f),P(3.8f,.18f,7),Deck,.15f);
            for(int side=-1;side<=1;side+=2) g.Box(P(-37,1.91f,side*2.8f),P(3.5f,.018f,.12f),Yellow);
            Mast(g,P(24,10.8f),4.8f,3.3f);Navigation(g,25,10.8f,8.0f);
        }
        static void Sailboat(Geometry g,MarineVesselParameters p)
        {
            const float deck=.8f;Hull(g,p,deck,White,Teak);Rails(g,p,deck,.62f,22,true);
            g.Box(P(.25f,1.05f),P(4.4f,.65f,2.5f),White,.5f);
            for(int side=-1;side<=1;side+=2) {
                for(int j=0;j<4;j++) g.Ellipsoid(P(-1.15f+j*.88f,1.10f,side*1.26f),P(.29f,.11f,.018f),Glass,20,10);
                g.Rope(P(.4f,15.5f),P(.3f,deck,side*1.7f),.04f,.009f,Steel,20);
                g.Rope(P(.4f,11.0f),P(-1.4f,deck,side*1.70f),.06f,.007f,Steel,20);
                for(int h=0;h<2;h++) g.Tube(P(.4f,7.0f+h*3.7f),P(.4f,7.0f+h*3.7f,side*1.15f),.025f,Steel);
                for(int i=0;i<3;i++) {var at=P(-2.3f+i*.8f,deck+.1f,side*1.38f);g.Tube(at,at+P(0,.18f),.09f,Steel,around:20);g.Ring(at+P(0,.12f),Vector3.up,.10f,.015f,RopeMat,18);}
                Cleat(g,P(4.7f,1.1f,side*.6f),.22f);
            }
            g.Tube(P(.4f,deck),P(.4f,15.5f),.085f,Steel,.045f,24);g.Tube(P(.38f,2.5f),P(-4.2f,2.5f),.065f,Steel,.045f,20);
            g.Sail(P(.33f,2.60f),P(.33f,15.05f),P(-4.0f,2.60f),.65f,Canvas);
            g.Sail(P(.65f,3.0f),P(.65f,14.8f),P(5.2f,1.2f),-.50f,White);
            for(int i=1;i<6;i++) {float t=i/6f;g.Rope(Vector3.Lerp(P(.33f,2.6f),P(.33f,15.05f),t),Vector3.Lerp(P(-4,2.6f),P(.33f,15.05f),t),-.1f,.008f,White,18);}
            g.Rope(P(.4f,15.5f),P(5.6f,1.1f),.02f,.010f,Steel,30);g.Rope(P(.4f,15.5f),P(-5.4f,.9f),.05f,.009f,Steel,30);
            g.Rope(P(-4.0f,2.5f),P(-3.6f,.85f),.15f,.012f,RopeMat);g.Box(P(-3.2f,.83f),P(2.25f,.04f,1.9f),Deck,.15f);
            g.Box(P(-3.2f,1.02f,-.8f),P(2.1f,.28f,.35f),Teak,.08f);g.Box(P(-3.2f,1.02f,.8f),P(2.1f,.28f,.35f),Teak,.08f);
            g.Ring(P(-4.1f,1.22f),Vector3.right,.32f,.018f,Steel,32);for(int spoke=0;spoke<6;spoke++) {float a=spoke*2*Mathf.PI/6;g.Tube(P(-4.1f,1.22f),P(-4.1f,1.22f+Mathf.Cos(a)*.31f,Mathf.Sin(a)*.31f),.009f,Steel);}
            g.Box(P(-.1f,-1.15f),P(1.8f,1.8f,.13f),DarkMetal,.05f);g.Ellipsoid(P(-.15f,-1.90f),P(.95f,.16f,.23f),Antifoul);
            g.Box(P(-5.15f,-.48f),P(.55f,1.35f,.07f),White,.025f);Fenders(g,10.5f,3.8f,.9f,3);Lifering(g,P(-5,1.25f,1.1f),.24f);Anchor(g,P(5.5f,.6f),.45f);
            Navigation(g,4.7f,1.0f,.63f);g.Ellipsoid(P(.4f,15.55f),P(.045f,.055f,.045f),NavWhite,12,8);
        }
    }
}
