/* SPDX-License-Identifier: EPL-2.0 */
#pragma once
#include <map>
#include <nlohmann/json.hpp>
#include "lotusim_mas/entity_spawner.hpp"
#include "lotusim_mas/scenario_types.hpp"

namespace lotusim::scenario {
// Only called on the Gazebo PreUpdate thread. Unity never submits positions:
// it acknowledges rendered frame N and requests frame N+1.
class DatasetTimeline {
public:
    DatasetTimeline(const ScenarioConfig& config, mas::EntitySpawner& spawner,
                    gz::sim::EntityComponentManager& ecm);
    nlohmann::json advance(int frame, double world_seconds);
    nlohmann::json describe() const;
    void clear();
    const std::string& token() const { return m_token; }
    std::size_t size() const { return m_entities.size(); }
private:
    const ScenarioConfig m_config;
    mas::EntitySpawner& m_spawner;
    gz::sim::EntityComponentManager& m_ecm;
    std::map<std::string, gz::sim::Entity> m_entities;
    std::string m_token;
    int m_frame{-1};
    nlohmann::json m_snapshot;
};
}
