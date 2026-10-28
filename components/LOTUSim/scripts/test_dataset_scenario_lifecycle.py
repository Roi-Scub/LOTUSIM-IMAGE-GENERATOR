#!/usr/bin/env python3
"""Exercise native scenario CREATE/poses/DELETE in an isolated Gazebo process.

Run inside the sourced LOTUSim devShell. Never connects to the user's ROS
domain and only terminates the test process it creates.
"""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import uuid

WORLD = """<?xml version="1.0"?><sdf version="1.10"><world name="dataset_cycle_check">
  <physics type="ode"><max_step_size>0.02</max_step_size><real_time_factor>1</real_time_factor></physics>
  <gravity>0 0 0</gravity>
  <spherical_coordinates><surface_model>EARTH_WGS84</surface_model><world_frame_orientation>ENU</world_frame_orientation>
    <latitude_deg>1.2421</latitude_deg><longitude_deg>103.7198</longitude_deg><elevation>0</elevation><heading_deg>0</heading_deg>
  </spherical_coordinates>
  <plugin filename="multi_agent_system_plugin" name="lotusim::gazebo::MultiAgentSystem"/>
  <plugin filename="render_plugin" name="lotusim::gazebo::RenderPlugin"><connection_protocol>ROS2</connection_protocol></plugin>
</world></sdf>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-dir", required=True)
    parser.add_argument("--cycles", type=int, default=8)
    args = parser.parse_args()
    if args.cycles < 1 or args.cycles > 30:
        parser.error("cycles must be between 1 and 30")
    plugin_dir = Path(args.plugin_dir).resolve()
    for library in ("libmulti_agent_system_plugin.so", "librender_plugin.so"):
        if not (plugin_dir / library).is_file():
            parser.error(f"missing test library: {library}")
    # Set these before importing rclpy. No CLI daemon or live-domain services.
    os.environ["ROS_DOMAIN_ID"] = "96"
    os.environ["GZ_PARTITION"] = "dataset-test-" + uuid.uuid4().hex
    os.environ["GZ_SIM_SYSTEM_PLUGIN_PATH"] = (
        str(plugin_dir) + ":" + os.environ.get("GZ_SIM_SYSTEM_PLUGIN_PATH", "")
    )
    os.environ["LD_LIBRARY_PATH"] = str(plugin_dir) + ":" + os.environ.get("LD_LIBRARY_PATH", "")
    import rclpy
    from rclpy.qos import QoSProfile, DurabilityPolicy
    from lotusim_msgs.msg import RendererCmd, VesselPositionArray
    from lotusim_msgs.srv import String
    from std_srvs.srv import Trigger

    output = Path(tempfile.mkdtemp(prefix="lotusim-scenario-cycle-test-"))
    world = output / "world.sdf"
    world.write_text(WORLD)
    result = {"passed": False, "cycles": [], "output": str(output), "isolated_ros_domain": 96}
    process = None
    node = None
    console = None
    try:
        console = (output / "gazebo-console.log").open("w")
        process = subprocess.Popen(
            ["gz", "sim", "-s", "-r", "-v", "1", str(world)],
            stdout=console,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        rclpy.init()
        node = rclpy.create_node("dataset_lifecycle_test")
        commands = []
        poses = []
        qos = QoSProfile(depth=100, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        node.create_subscription(
            RendererCmd, "/dataset_cycle_check/renderer_cmd", commands.append, qos
        )
        node.create_subscription(
            VesselPositionArray, "/dataset_cycle_check/renderer_poses", poses.append, qos
        )
        launch = node.create_client(String, "/dataset_cycle_check/launch_scenario")
        stop = node.create_client(Trigger, "/dataset_cycle_check/stop_scenario")

        def wait(predicate, label, timeout=12):
            deadline = time.monotonic() + timeout
            while not predicate():
                if process.poll() is not None:
                    raise RuntimeError("test Gazebo exited: " + str(process.returncode))
                if time.monotonic() > deadline:
                    raise TimeoutError(label)
                rclpy.spin_once(node, timeout_sec=0.05)

        wait(
            lambda: launch.service_is_ready() and stop.service_is_ready(),
            "scenario services unavailable",
            30,
        )
        for cycle in range(args.cycles):
            commands.clear()
            poses.clear()
            request = String.Request()
            request.data = "BuoyDatasetPilot.yaml"
            future = launch.call_async(request)
            wait(future.done, "launch response timeout")
            response = future.result()
            if not response.success:
                raise RuntimeError("launch rejected: " + response.message)
            wait(
                lambda: any(
                    c.cmd_type == 0
                    and c.vessel_name == "Buoy_001"
                    and c.renderer_obj_name == "buoy"
                    for c in commands
                ),
                "missing CREATE Buoy_001",
            )
            wait(
                lambda: any(any(v.vessel_name == "Buoy_001" for v in p.vessels) for p in poses),
                "missing pose Buoy_001",
            )
            duplicate = launch.call_async(request)
            wait(duplicate.done, "duplicate launch response timeout")
            if duplicate.result().success:
                raise AssertionError("concurrent scenario was accepted")
            future = stop.call_async(Trigger.Request())
            wait(future.done, "stop response timeout")
            if not future.result().success:
                raise RuntimeError("stop rejected: " + future.result().message)
            wait(
                lambda: any(c.cmd_type == 1 and c.vessel_name == "Buoy_001" for c in commands),
                "missing DELETE Buoy_001",
            )
            poses.clear()
            wait(
                lambda: poses and len(poses[-1].vessels) == 0, "pose list did not clear after stop"
            )
            result["cycles"].append(
                {
                    "cycle": cycle + 1,
                    "create": True,
                    "pose": True,
                    "duplicate_rejected": True,
                    "delete": True,
                }
            )
            print(
                "PASS cycle", cycle + 1, "CREATE / pose / duplicate rejection / DELETE", flush=True
            )
        result["passed"] = True
    except Exception as error:
        result["error"] = str(error)
        raise
    finally:
        (output / "result.json").write_text(json.dumps(result, indent=2))
        if node is not None:
            node.destroy_node()
            rclpy.shutdown()
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
        if console is not None:
            console.close()
        print("TEST_RESULT", output / "result.json", flush=True)


if __name__ == "__main__":
    main()
