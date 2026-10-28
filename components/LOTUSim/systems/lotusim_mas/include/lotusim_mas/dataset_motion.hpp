/* SPDX-License-Identifier: EPL-2.0 */
#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include "lotusim_mas/scenario_types.hpp"

namespace lotusim::scenario {
struct MotionSample { std::array<double,3> position{},velocity{}; double yaw{}; };
// Dataset kinematics only; no flight controller, aerodynamic or weapon model.
// Position and velocity are continuous at the bounded turn's two joins.
inline MotionSample sampleMotion(const Agent::Trajectory& t,double time,double heading_deg=0)
{
    constexpr double pi=3.14159265358979323846;
    const double dt=time-t.center_seconds,w=t.yaw_rate_deg_s*pi/180.0;
    const double q=(t.bounded_turn?std::clamp(time,t.turn_start_seconds,t.turn_end_seconds):time)-t.center_seconds;
    const auto velocity=[&](double at){const double a=w*at;return std::array<double,2>{std::cos(a)*t.velocity[0]-std::sin(a)*t.velocity[1],std::sin(a)*t.velocity[0]+std::cos(a)*t.velocity[1]};};
    double x=std::abs(w)<1e-9?t.velocity[0]*q:(t.velocity[0]*std::sin(w*q)+t.velocity[1]*(std::cos(w*q)-1))/w;
    double y=std::abs(w)<1e-9?t.velocity[1]*q:(t.velocity[0]*(1-std::cos(w*q))+t.velocity[1]*std::sin(w*q))/w;
    if(t.bounded_turn){
        const double before=std::min(0.0,time-t.turn_start_seconds),after=std::max(0.0,time-t.turn_end_seconds);
        const auto a=velocity(t.turn_start_seconds-t.center_seconds),b=velocity(t.turn_end_seconds-t.center_seconds);
        x+=before*a[0]+after*b[0];y+=before*a[1]+after*b[1];
    }
    const auto v=velocity(q);MotionSample result;
    result.position={t.center[0]+x,t.center[1]+y,t.center[2]+t.velocity[2]*dt};result.velocity={v[0],v[1],t.velocity[2]};
    result.yaw=std::hypot(v[0],v[1])>1e-8?std::atan2(v[1],v[0]):heading_deg*pi/180.0+w*q;
    return result;
}
}
