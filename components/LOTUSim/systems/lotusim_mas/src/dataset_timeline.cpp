/* SPDX-License-Identifier: EPL-2.0 */
#include "lotusim_mas/dataset_timeline.hpp"
#include "lotusim_mas/dataset_motion.hpp"
#include <chrono>
#include <random>
#include <sstream>
#include <stdexcept>
#include <gz/sim/components/Name.hh>
#include <gz/sim/components/Pose.hh>
#include <gz/sim/components/Static.hh>

namespace lotusim::scenario {
using json = nlohmann::json;
DatasetTimeline::DatasetTimeline(const ScenarioConfig& config, mas::EntitySpawner& spawner,
                                 gz::sim::EntityComponentManager& ecm)
    : m_config(config), m_spawner(spawner), m_ecm(ecm)
{
    std::ostringstream id;
    id << std::hex << std::chrono::steady_clock::now().time_since_epoch().count()
       << std::random_device{}();
    m_token = id.str();
    // Refuse collisions before creating anything; never rename a dataset ID.
    for (const auto& agent : config.agents)
        if (m_ecm.EntityByComponents(gz::sim::components::Name(agent.name)) != gz::sim::kNullEntity)
            throw std::runtime_error("Dataset actor already exists: " + agent.name);
}
json DatasetTimeline::describe() const
{
    const auto& d = *m_config.dataset_sequence;
    return {{"schema", "lotusim-dataset-step-1"}, {"scenario", m_config.name},
            {"runId", m_token}, {"planId", d.plan_id}, {"observer", d.observer},
            {"fps", d.fps}, {"frames", d.frames}, {"frame", m_frame},
            {"motionSource", "LOTUSim ENU kinematic timeline"}};
}
json DatasetTimeline::advance(int frame, double world_seconds)
{
    const auto& d = *m_config.dataset_sequence;
    if (frame == m_frame && frame >= 0) return m_snapshot; // Safe retry, no second spawn.
    if (frame < 0 || frame >= d.frames || frame != m_frame + 1)
        throw std::invalid_argument("Expected next dataset frame " + std::to_string(m_frame + 1));
    const double time = double(frame) / d.fps;
    json objects = json::array();
    for (const auto& agent : m_config.agents) {
        const auto& t = *agent.trajectory;
        auto found = m_entities.find(agent.name);
        if (time < t.start_seconds || time >= t.end_seconds) {
            if (found != m_entities.end()) {
                lotusim_msgs::msg::MASCmd remove; remove.entity = found->second;
                if (!m_spawner.deleteEntity(remove)) throw std::runtime_error("Dataset deletion failed");
                m_entities.erase(found);
            }
            continue;
        }
        if (found == m_entities.end()) {
            lotusim_msgs::msg::MASCmd create;
            create.model_name = agent.model; create.vessel_name = agent.name;
            create.sdf_string = agent.lotus_param;
            create.vessel_position.orientation.w = 1;
            auto result = m_spawner.addEntity(create);
            if (!result || std::get<0>(*result) == gz::sim::kNullEntity)
                throw std::runtime_error("Cannot create dataset actor: " + agent.name);
            auto entity = std::get<0>(*result);
            m_entities[agent.name] = entity;
            if (std::get<1>(*result) != agent.name) throw std::runtime_error("Dataset ID was renamed");
            const auto* stationary = m_ecm.Component<gz::sim::components::Static>(entity);
            if (!stationary || !stationary->Data())
                throw std::runtime_error("Dataset kinematic actors must use static SDF models: " + agent.model);
            found = m_entities.find(agent.name);
        }
        const auto sample=sampleMotion(t,time,agent.heading);
        gz::math::Pose3d pose(sample.position[0],sample.position[1],sample.position[2],0,0,sample.yaw);
        if (!m_ecm.Component<gz::sim::components::Pose>(found->second))
            throw std::runtime_error("Dataset actor lost its ECM pose");
        m_ecm.SetComponentData<gz::sim::components::Pose>(found->second, pose);
        m_ecm.SetChanged(found->second, gz::sim::components::Pose::typeId, gz::sim::ComponentState::OneTimeChange);
        // Read back the actual ECM state, not just the requested transform.
        pose = m_ecm.Component<gz::sim::components::Pose>(found->second)->Data();
        objects.push_back({{"instance", agent.name}, {"model", agent.model},
            {"entity", found->second}, {"position", {{"x",pose.X()},{"y",pose.Y()},{"z",pose.Z()}}},
            {"rotation", {{"x",pose.Rot().X()},{"y",pose.Rot().Y()},{"z",pose.Rot().Z()},{"w",pose.Rot().W()}}},
            {"velocity", {{"x",sample.velocity[0]},{"y",sample.velocity[1]},{"z",sample.velocity[2]}}}});
    }
    m_frame = frame;
    m_snapshot = describe();
    m_snapshot["timeSeconds"] = time;
    m_snapshot["worldTimeSeconds"] = world_seconds;
    m_snapshot["objects"] = std::move(objects);
    return m_snapshot;
}
void DatasetTimeline::clear()
{
    for (const auto& item : m_entities) {
        lotusim_msgs::msg::MASCmd remove; remove.entity = item.second;
        m_spawner.deleteEntity(remove);
    }
    m_entities.clear();
}
}
