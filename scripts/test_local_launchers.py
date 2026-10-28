#!/usr/bin/env python3
"""Fixture-only local launcher contracts. Never starts Docker, Unity or a service."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent


def load_source(name):
    """Load a neighbouring source without creating __pycache__ in its directory."""
    path = HERE / (name + '.py')
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), module.__dict__)
    return module


class LauncherTests(unittest.TestCase):
    def test_runtime_dashboard_can_be_selected_without_unity_project(self):
        self.fixture_file('runtime/LOTUSim/tools/ops_dashboard.py')
        self.assertFalse(self.unity.exists())
        self.assertEqual(self.dashboard.default_roots(), (self.core, self.unity))
        with (
            mock.patch.object(sys, 'argv', ['start_dashboard.py', '--no-docker']),
            mock.patch.object(self.dashboard.os, 'execv') as execute,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.dashboard.main()
        self.assertIn('--no-docker', execute.call_args.args[1])

    def test_nonunity_profile_never_launches_unity_or_an_arbitrary_engine(self):
        with (
            mock.patch.object(
                self.stack, 'engine_profile', return_value={'id': 'godot', 'label': 'Godot'}
            ),
            mock.patch.object(self.stack.subprocess, 'run') as run,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.stack.open_renderer()
        run.assert_not_called()

    def test_dashboard_preflight_needs_no_unity_docker_or_gazebo(self):
        self.fixture_file('runtime/LOTUSim/tools/ops_dashboard.py')
        with mock.patch.object(self.stack.shutil, 'which', return_value=None):
            self.stack.preflight('dashboard')

    def test_nonunity_full_stack_preflight_does_not_require_unity_project(self):
        self.fixture_file('runtime/LOTUSim/install/setup.bash')
        self.fixture_file('runtime/LOTUSim/assets/worlds/maritime_dataset.world')
        with (
            mock.patch.object(
                self.stack, 'engine_profile', return_value={'id': 'godot', 'label': 'Godot'}
            ),
            mock.patch.object(self.stack.shutil, 'which', return_value='/fixture/docker'),
        ):
            self.stack.preflight()

    def setUp(self):
        self.stack = load_source('start_local_stack')
        self.dashboard = load_source('start_dashboard')
        self.temporary = tempfile.TemporaryDirectory(prefix='lotusim-launcher-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.core = self.root / 'runtime/LOTUSim'
        self.unity = self.root / 'runtime/LOTUSim-Unity-modules'
        for module in (self.stack, self.dashboard):
            module.ROOT = self.root
        self.stack.CORE = self.core
        self.stack.UNITY = self.unity

    def fixture_file(self, relative, content='fixture\n'):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
        return target

    def docker_info(self, source=None, running=False):
        return {
            'Mounts': [{'Source': str(source or self.core), 'Destination': '/workspace'}],
            'State': {'Running': running, 'Status': 'running' if running else 'exited'},
        }

    @staticmethod
    def result(stdout='', code=0):
        return subprocess.CompletedProcess(['fixture'], code, stdout, '')

    @staticmethod
    def tcp_line(port, state='0A', ipv6=False):
        address = '00000000000000000000000000000000' if ipv6 else '00000000'
        return '  0: {}:{:04X} {}:0000 {} 00000000:00000000 00:00000000 00000000 0 0 1\n'.format(
            address, port, address, state
        )

    def test_complete_runtime_defaults_are_selected_together(self):
        self.fixture_file('runtime/LOTUSim/flake.nix')
        self.fixture_file('runtime/LOTUSim-Unity-modules/ProjectSettings/ProjectVersion.txt')
        self.assertEqual(self.dashboard.default_roots(), (self.core, self.unity))

    def test_incomplete_runtime_does_not_mix_overlay_and_live_roots(self):
        expected = (
            self.root / 'components/LOTUSim',
            self.root / 'components/LOTUSim-Unity-modules',
        )
        self.assertEqual(self.dashboard.default_roots(), expected)
        self.fixture_file('runtime/LOTUSim/flake.nix')
        self.assertEqual(self.dashboard.default_roots(), expected)

    def test_dashboard_executes_source_from_selected_runtime(self):
        self.fixture_file('runtime/LOTUSim/flake.nix')
        self.fixture_file('runtime/LOTUSim-Unity-modules/ProjectSettings/ProjectVersion.txt')
        server = self.fixture_file('runtime/LOTUSim/tools/ops_dashboard.py')
        with (
            mock.patch.object(sys, 'argv', ['start_dashboard.py', '--no-docker']),
            mock.patch.object(self.dashboard.os, 'execv') as execute,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.dashboard.main()
        arguments = execute.call_args.args[1]
        self.assertEqual(arguments[:2], [sys.executable, str(server)])
        self.assertEqual(arguments[arguments.index('--core') + 1], str(self.core))
        self.assertEqual(arguments[arguments.index('--unity') + 1], str(self.unity))
        self.assertIn('--no-docker', arguments)

    def test_wrong_docker_bind_refuses_even_with_start_requested(self):
        info = self.docker_info(self.root / 'old/LOTUSim')
        with mock.patch.object(
            self.stack.subprocess, 'run', return_value=self.result(json.dumps([info]))
        ) as run:
            with self.assertRaisesRegex(RuntimeError, 'Wrong /workspace mount'):
                self.stack.container_info(start=True)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ['docker', 'inspect', 'lotusim-dev'])

    def test_missing_docker_bind_refuses_without_starting(self):
        info = self.docker_info()
        info['Mounts'] = []
        with mock.patch.object(
            self.stack.subprocess, 'run', return_value=self.result(json.dumps([info]))
        ) as run:
            with self.assertRaisesRegex(RuntimeError, 'Wrong /workspace mount'):
                self.stack.container_info(start=True)
        run.assert_called_once()

    def test_correct_stopped_container_can_be_started_after_mount_check(self):
        info = self.docker_info()
        with mock.patch.object(
            self.stack.subprocess,
            'run',
            side_effect=[self.result(json.dumps([info])), self.result()],
        ) as run:
            self.assertEqual(self.stack.container_info(start=True), info)
        self.assertEqual(run.call_args_list[1].args[0], ['docker', 'start', 'lotusim-dev'])

    def test_docker_host_proxies_do_not_count_as_running_ros_or_web(self):
        with (
            mock.patch.object(self.stack, 'listeners', return_value=['12345']) as host,
            mock.patch.object(self.stack.subprocess, 'run', return_value=self.result('')) as run,
        ):
            self.assertFalse(self.stack.service_active('ros'))
            self.assertFalse(self.stack.service_active('web'))
        host.assert_not_called()
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertEqual(call.args[0][:3], ['docker', 'exec', 'lotusim-dev'])
            self.assertIn('/proc/net/tcp', call.args[0][-1])

    def test_container_listen_ipv4_and_ipv6_are_recognised(self):
        for service, port in (('ros', 10000), ('web', 8080)):
            for ipv6 in (False, True):
                with (
                    self.subTest(service=service, ipv6=ipv6),
                    mock.patch.object(
                        self.stack.subprocess,
                        'run',
                        return_value=self.result(self.tcp_line(port, ipv6=ipv6)),
                    ),
                ):
                    self.assertTrue(self.stack.service_active(service))

    def test_established_socket_or_different_port_is_not_a_server(self):
        fixtures = (
            self.tcp_line(10000, state='01'),
            self.tcp_line(8080),
            '  sl local_address rem_address st tx_queue rx_queue\n',
        )
        for content in fixtures:
            with (
                self.subTest(content=content),
                mock.patch.object(self.stack.subprocess, 'run', return_value=self.result(content)),
            ):
                self.assertFalse(self.stack.service_active('ros'))

    def test_docker_inspection_failure_never_reports_server_stopped(self):
        with mock.patch.object(
            self.stack.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['docker'])
        ):
            with self.assertRaises((RuntimeError, subprocess.CalledProcessError)):
                self.stack.service_active('ros')

    def test_dashboard_listener_uses_lsof_without_connecting(self):
        with mock.patch.object(
            self.stack.subprocess, 'run', return_value=self.result('42\n42\n87\n')
        ) as run:
            self.assertTrue(self.stack.service_active('dashboard'))
        command = run.call_args.args[0]
        self.assertEqual(command, ['/usr/sbin/lsof', '-t', '-iTCP:8766', '-sTCP:LISTEN'])

    def test_sim_probe_handles_ruby_gazebo_wrapper_via_cmdline(self):
        with mock.patch.object(
            self.stack.subprocess, 'run', return_value=self.result(code=42)
        ) as run:
            self.assertTrue(self.stack.service_active('sim'))
        probe = run.call_args.args[0][-1]
        self.assertIn(
            'cmdline',
            probe,
            'Gazebo may have comm=ruby; checking comm alone misses the active world',
        )
        self.assertIn('.gz-wrapped', probe)
        self.assertIn('sim', probe)

    def test_sim_inspection_unknown_is_fail_closed(self):
        for code in (1, 125):
            with (
                self.subTest(code=code),
                mock.patch.object(
                    self.stack.subprocess, 'run', return_value=self.result(code=code)
                ),
            ):
                with self.assertRaises(RuntimeError):
                    self.stack.service_active('sim')

    def test_probes_never_open_tcp_clients(self):
        with (
            mock.patch('socket.socket', side_effect=AssertionError('No TCP probe allowed')),
            mock.patch(
                'socket.create_connection', side_effect=AssertionError('No TCP probe allowed')
            ),
            mock.patch.object(self.stack.subprocess, 'run', return_value=self.result('')) as run,
        ):
            for service in self.stack.SERVICES:
                self.assertFalse(self.stack.service_active(service))
        for call in run.call_args_list:
            command = call.args[0]
            self.assertIn(command[0], ('/usr/sbin/lsof', 'docker'))
            probe = command[-1]
            for forbidden in ('nc ', 'curl ', 'telnet ', '/dev/tcp/', 'create_connection'):
                self.assertNotIn(forbidden, probe)

    def test_service_bootstrap_fails_closed_before_sourcing(self):
        for service in ('ros', 'sim'):
            command = self.stack.command_for(service)
            self.assertEqual(
                command[:7], ['docker', 'exec', '-it', '-w', '/workspace', 'lotusim-dev', 'nix']
            )
            shell = command[-1]
            self.assertTrue(shell.startswith('set -e'), shell)
            self.assertLess(shell.index('set -e'), shell.index('source '))
            self.assertIn('source /workspace/install/setup.bash;', shell)
        self.assertIn('maritime_dataset.world', self.stack.command_for('sim')[-1])
        self.assertIn('ROS_TCP_PORT:=10000', self.stack.command_for('ros')[-1])

    def test_inactive_services_open_executable_documents_without_typing_into_prompts(self):
        with (
            mock.patch.object(self.stack, 'preflight'),
            mock.patch.object(self.stack, 'container_info'),
            mock.patch.object(self.stack, 'service_active', return_value=False),
            mock.patch.object(self.stack.subprocess, 'run', return_value=self.result()) as run,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.stack.open_stack()
        scripts = [
            call.args[0]
            for call in run.call_args_list
            if call.args[0][:4] == ['open', '-g', '-a', 'Terminal']
        ]
        self.assertEqual(len(scripts), len(self.stack.SERVICES))
        self.assertEqual(
            [Path(command[-1]).name for command in scripts],
            ['run_' + service + '.command' for service in self.stack.SERVICES],
        )
        self.assertFalse(any(call.args[0][0] == 'osascript' for call in run.call_args_list))

    def test_active_services_do_not_open_new_terminal_commands(self):
        with (
            mock.patch.object(self.stack, 'preflight'),
            mock.patch.object(self.stack, 'container_info'),
            mock.patch.object(self.stack, 'service_active', return_value=True),
            mock.patch.object(self.stack.subprocess, 'run', return_value=self.result()) as run,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.stack.open_stack()
        self.assertEqual([call.args[0] for call in run.call_args_list], [['pgrep', '-x', 'Unity']])

    def test_existing_service_refuses_before_spawning_child(self):
        with (
            mock.patch.object(self.stack, 'preflight'),
            mock.patch.object(self.stack, 'container_info'),
            mock.patch.object(self.stack, 'service_active', return_value=True),
            mock.patch.object(self.stack.subprocess, 'Popen') as spawn,
        ):
            with self.assertRaisesRegex(RuntimeError, 'already active'):
                self.stack.run_service('sim')
        spawn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
