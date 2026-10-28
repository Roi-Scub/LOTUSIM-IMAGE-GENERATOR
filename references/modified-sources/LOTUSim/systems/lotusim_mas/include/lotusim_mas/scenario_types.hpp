/*
 * Copyright (c) 2025 Naval Group
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * https://www.eclipse.org/legal/epl-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0
 */
#ifndef LOTUSIM_SCENARIO_TYPES_HH_
#define LOTUSIM_SCENARIO_TYPES_HH_

#include <optional>
#include <array>
#include <string>
#include <vector>

namespace lotusim {

struct GeoPoint {
    double latitude{0.0};
    double longitude{0.0};
    double altitude{0.0};
};

struct Agent {
    std::string name;  ///< key from YAML map (e.g. "lrauv1")
    std::string model; ///< model asset name
    GeoPoint position;
    double heading{0.0}; /// heading → yaw (Z-up, East=0, right-hand rule)

    /// Fully-formed <lotus_param>…</lotus_param> XML string,
    /// built by ScenarioParser from physics_interface + render_interface.
    std::string lotus_param;

    // Optional dataset-only trajectory. ENU metres; +X is the model's nose.
    struct Trajectory {
        std::array<double, 3> center{}, velocity{};
        double center_seconds{0}, start_seconds{0}, end_seconds{0};
        double yaw_rate_deg_s{0}; // Constant ENU turn rate about center_seconds.
        bool bounded_turn{false}; // Straight before/after a tangent-continuous turn.
        double turn_start_seconds{0}, turn_end_seconds{0};
    };
    std::optional<Trajectory> trajectory;
};

struct ScenarioConfig {
    std::string name;

    std::string time_of_day; ///< "HH:MM"
    std::string date;        ///< "YYYY-MM-DD"
    GeoPoint reference_position;

    // TODO: Fill this up along with the environment system
    // Environment environment;

    std::vector<Agent> agents; ///< ordered list, name stored inside Agent
    struct DatasetSequence {
        std::string plan_id, observer;
        int fps{30}, frames{1800};
    };
    std::optional<DatasetSequence> dataset_sequence;
};

} // namespace lotusim
#endif // LOTUSIM_SCENARIO_TYPES_HH_
