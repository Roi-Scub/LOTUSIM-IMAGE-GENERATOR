#!/usr/bin/env python3
"""Temporary real Gazebo + ROS TCP endpoint for the isolated Unity fixture.

Never uses domain 0 or port 10000. Terminates only processes created here.
"""

import argparse
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
import uuid
from tests.python.integration.test_dataset_scenario_lifecycle import WORLD


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin-dir', required=True)
    parser.add_argument(
        '--output',
        required=True,
        help='Fresh shared fixture directory, also used by the Unity test',
    )
    args = parser.parse_args()
    plugins = Path(args.plugin_dir).resolve()
    if not (plugins / 'libmulti_agent_system_plugin.so').is_file():
        parser.error('missing MAS plugin')
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    stop = root / 'stop-test-server'
    if stop.exists():
        raise RuntimeError('Use a fresh bridge fixture directory; stop marker exists')
    check = socket.socket()
    check.bind(('127.0.0.1', 10001))
    check.close()
    os.environ.update(
        ROS_DOMAIN_ID='97',
        GZ_PARTITION='unity-bridge-' + uuid.uuid4().hex,
        LOTUSIM_SCENARIOS_PATH=str(root),
        GZ_SIM_SYSTEM_PLUGIN_PATH=str(plugins)
        + ':/workspace/install/lib:'
        + os.environ.get('GZ_SIM_SYSTEM_PLUGIN_PATH', ''),
        LD_LIBRARY_PATH=str(plugins)
        + ':/workspace/install/lib:'
        + os.environ.get('LD_LIBRARY_PATH', ''),
    )
    (root / 'world.sdf').write_text(WORLD.replace('dataset_cycle_check', 'lotusim_test_bridge'))
    children = []
    try:
        for name, command in [
            ('gazebo', ['gz', 'sim', '-s', '-r', '-v', '1', str(root / 'world.sdf')]),
            (
                'endpoint',
                [
                    'ros2',
                    'run',
                    'ros_tcp_endpoint',
                    'default_server_endpoint',
                    '--ros-args',
                    '-p',
                    'ROS_IP:=0.0.0.0',
                    '-p',
                    'ROS_TCP_PORT:=10001',
                ],
            ),
        ]:
            with (root / (name + '.log')).open('w') as stream:
                children.append(
                    subprocess.Popen(
                        command, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True
                    )
                )
        deadline = time.monotonic() + 900
        print(
            'BRIDGE_TEST_STARTED domain=97, namespace=lotusim_test_bridge, endpoint=10001',
            flush=True,
        )
        while not stop.exists() and time.monotonic() < deadline:
            if any(child.poll() is not None for child in children):
                raise RuntimeError('isolated bridge child exited; inspect fixture logs')
            time.sleep(0.2)
    finally:
        for child in children:
            if child.poll() is not None:
                continue
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
                os.killpg(child.pid, sig)
                try:
                    child.wait(timeout=4)
                    break
                except subprocess.TimeoutExpired:
                    pass
        print('BRIDGE_TEST_STOPPED; user Gazebo and endpoint untouched', flush=True)


if __name__ == '__main__':
    main()
