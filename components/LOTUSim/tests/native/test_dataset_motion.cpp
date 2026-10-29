#include <cassert>
#include <cmath>
#include <iostream>
#include "lotusim_mas/dataset_motion.hpp"
int main() {
    lotusim::Agent::Trajectory t;
    t.center = {100, 200, 70};
    t.velocity = {0, 400.0 / 3.6, 0};
    t.center_seconds = 40;
    t.start_seconds = 0;
    t.end_seconds = 180;
    t.yaw_rate_deg_s = -5;
    t.bounded_turn = true;
    t.turn_start_seconds = 36;
    t.turn_end_seconds = 44;
    for (double time : {0., 35., 36., 36.001, 39., 40., 44., 44.001, 90., 179.}) {
        auto p = lotusim::scenario::sampleMotion(t, time),
             a = lotusim::scenario::sampleMotion(t, time - 1e-5),
             b = lotusim::scenario::sampleMotion(t, time + 1e-5);
        assert(std::abs(std::hypot(p.velocity[0], p.velocity[1]) - 400.0 / 3.6) < 1e-9);
        for (int i = 0; i < 3; i++)
            assert(std::abs((b.position[i] - a.position[i]) / 2e-5 - p.velocity[i]) < 1e-4);
        assert(p.position[2] == 70);
    }
    for (double join : {36., 44.}) {
        auto a = lotusim::scenario::sampleMotion(t, join - 1e-7),
             b = lotusim::scenario::sampleMotion(t, join + 1e-7);
        assert(std::hypot(a.position[0] - b.position[0], a.position[1] - b.position[1]) < .0001);
        assert(std::hypot(a.velocity[0] - b.velocity[0], a.velocity[1] - b.velocity[1]) < .0001);
    }
    t.bounded_turn = false;
    t.yaw_rate_deg_s = 0;
    auto linear = lotusim::scenario::sampleMotion(t, 42);
    assert(linear.position[0] == 100);
    assert(std::abs(linear.position[1] - 200 - 2 * 400.0 / 3.6) < 1e-9);
    std::cout
        << "PASS bounded turn position/velocity continuity, 400 km/h units and legacy straight path\n";
}
