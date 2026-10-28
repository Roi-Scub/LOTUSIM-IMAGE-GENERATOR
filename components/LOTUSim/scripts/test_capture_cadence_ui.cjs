/* Pure schedule preview contracts; no network, engine or filesystem writes. */
'use strict';
const path=require('node:path'),assert=require('node:assert/strict'),ui=path.resolve(process.argv[2]||path.join(__dirname,'../tools/ops_dashboard_ui'));
const settings=require(path.join(ui,'settings.js')).captureCadence,traffic=require(path.join(ui,'traffic.js')).captureCadence;let checks=0;
const check=(condition,message)=>{assert.ok(condition,message);checks++;};
for(const calculate of [settings,traffic]){
  const interval=calculate(60,{mode:'interval',intervalSeconds:2});check(interval.count===30&&interval.frames[0]===0&&interval.frames.at(-1)===1740&&interval.effectiveTimesSeconds.at(-1)===58,'60 simulated seconds / 2 seconds yields exactly 30 photos from 0 through 58');
  const count=calculate(60,{mode:'count',count:30});check(JSON.stringify(count.frames)===JSON.stringify(interval.frames),'count allocation includes t0 and excludes duration');
  const fractional=calculate(60,{mode:'interval',intervalSeconds:.05});check(fractional.count===1200&&fractional.frames.slice(0,6).join(',')==='0,2,3,5,6,8','half frames round upward from absolute decimal times, without cumulative drift');
  check(fractional.frames.at(-1)===1799&&fractional.maxQuantizationErrorSeconds<=1/60+1e-12,'fractional interval stays inside the final frame and quantization error bound');
  check(calculate(60,{mode:'interval',intervalSeconds:100}).count===1,'an interval longer than the episode keeps only t0');
  check(calculate(60,{mode:'count',count:1}).effectiveTimesSeconds[0]===0,'one requested photo is captured at t0');
  check(calculate(4.01,{mode:'count',count:120}).simulationFrames===121,'fractional duration uses ceil(duration * 30) frames');
  check(calculate(128/30,{mode:'count',count:128}).simulationFrames===128,'engine frame capacity uses Number ceil(duration * 30), not an expanded decimal rational ceiling');
  const boundary=calculate(128/30,{mode:'interval',intervalSeconds:1/30});check(boundary.count===128&&boundary.discardedAtOrAfterEndCount===1,'one final decimal candidate is excluded at a fractional frame boundary without shifting earlier takes');
  check(calculate(180,null).capture===null,'legacy mode emits no new capture option');
  for(const [duration,request]of [[60,{mode:'count',count:2001}],[4,{mode:'count',count:121}],[60,{mode:'count',count:0}],[60,{mode:'count',count:2.2}],[60,{mode:'interval',intervalSeconds:0}],[60,{mode:'interval',intervalSeconds:.01}],[600,{mode:'interval',intervalSeconds:.05}],[Infinity,{mode:'count',count:1}],[3,{mode:'count',count:1}],[60,{mode:'other'}]]){assert.throws(()=>calculate(duration,request));checks++;}
}
for(const duration of [4,4.01,60,60.05,180,599.999])for(const request of [{mode:'count',count:3},{mode:'count',count:30},{mode:'interval',intervalSeconds:.3},{mode:'interval',intervalSeconds:2}])check(JSON.stringify(settings(duration,request))===JSON.stringify(traffic(duration,request)),'both generation panels use the same preview contract');
console.log(checks+' capture-cadence UI checks passed');
