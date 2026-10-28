#!/usr/bin/env python3
"""Open this Mac's services and the selected supported editor; never starts Play.

Usage: python3 scripts/start_local_stack.py [open|status|run SERVICE]
The Docker container must already be provisioned. Its mount is checked before use.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / 'runtime/LOTUSim'
UNITY = ROOT / 'runtime/LOTUSim-Unity-modules'
CONTAINER = 'lotusim-dev'
UNITY_APP = Path('/Applications/Unity/Hub/Editor/2022.3.18f1/Unity.app')
SERVICES = ('dashboard', 'ros', 'sim', 'web')
PORTS = {'dashboard': 8766, 'ros': 10000, 'web': 8080}
NIX = ['nix', '--extra-experimental-features', 'nix-command flakes',
       '--option', 'filter-syscalls', 'false']


def container_info(start=False):
    result = subprocess.run(['docker', 'inspect', CONTAINER], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Missing lotusim-dev container. See docs/SESSION_LOCALE.md.')
    info = json.loads(result.stdout)[0]
    mount = next((item for item in info['Mounts'] if item['Destination'] == '/workspace'), None)
    if not mount or Path(mount['Source']).resolve() != CORE.resolve():
        raise RuntimeError('Wrong /workspace mount. No service started; do not use the old container.')
    if start and not info['State']['Running']:
        subprocess.run(['docker', 'start', CONTAINER], check=True)
    return info


def listeners(port):
    # Never connect to port 10000: a probe would create a phantom Unity client.
    result = subprocess.run(['/usr/sbin/lsof', '-t', '-iTCP:' + str(port), '-sTCP:LISTEN'],
                            capture_output=True, text=True)
    return sorted(set(result.stdout.split()))


def service_active(service):
    if service == 'dashboard':
        return bool(listeners(PORTS[service]))
    if service == 'sim':
        probe = subprocess.run(['docker', 'exec', CONTAINER, 'sh', '-c',
            'for p in /proc/[0-9]*/comm; do read n < "$p"; '
            'case "$n" in .gz-wrapped|gz-sim-server) exit 42;; '
            'ruby) a=$(tr "\\000" " " < "${p%comm}cmdline" 2>/dev/null) || continue; '
            'case "$a" in *".gz-wrapped sim"*) exit 42;; esac;; esac; done'],
            capture_output=True)
        if probe.returncode not in (0, 42):
            raise RuntimeError('Unable to check the current Gazebo world.')
        return probe.returncode == 42
    # Docker Desktop listens on published host ports even when no server is
    # running inside. Inspect LISTEN sockets in the container, never probe TCP.
    probe = subprocess.run(['docker', 'exec', CONTAINER, 'sh', '-c',
                            'cat /proc/net/tcp /proc/net/tcp6'],
                           capture_output=True, text=True, check=True)
    for line in probe.stdout.splitlines():
        fields = line.split()
        if len(fields) > 3 and fields[3] == '0A':
            if int(fields[1].rsplit(':', 1)[-1], 16) == PORTS[service]:
                return True
    return False


def command_for(service):
    if service == 'dashboard':
        return [sys.executable, str(ROOT / 'scripts/start_dashboard.py')]
    prefix = ['docker', 'exec', '-it', '-w', '/workspace', CONTAINER]
    if service == 'web':
        return prefix + NIX + ['run', '.#ui']
    shell = 'set -e; source /workspace/install/setup.bash; '
    if service == 'sim':
        shell += 'export LTTNG_UST_REGISTER_TIMEOUT=0; exec mise run sim --debug maritime_dataset.world'
    else:
        shell += ('source /root/.local/share/lotusim/ros_tcp_endpoint_ws/install/setup.bash; '
                  'exec ros2 run ros_tcp_endpoint default_server_endpoint --ros-args '
                  '-p ROS_IP:=0.0.0.0 -p ROS_TCP_PORT:=10000')
    return prefix + NIX + ['develop', '-c', 'bash', '-lc', shell]


def engine_profile():
    tools = CORE / 'tools'
    if not (tools / 'engine_registry.py').is_file():
        return {'id': 'unity', 'label': 'Unity', 'mode': 'legacy_adapter'}
    location = str(tools)
    if location not in sys.path:
        sys.path.insert(0, location)
    from engine_registry import EngineRegistry
    return EngineRegistry(CORE, UNITY).selection()


def preflight(service=None):
    if service == 'dashboard':
        if not (CORE / 'tools/ops_dashboard.py').is_file():
            raise RuntimeError('Dashboard source is missing from the core runtime.')
        return
    required_files = [CORE / 'install/setup.bash', CORE / 'assets/worlds/maritime_dataset.world']
    if engine_profile()['id'] == 'unity':
        required_files.append(UNITY / 'ProjectSettings/ProjectVersion.txt')
    for required in required_files:
        if not required.is_file():
            raise RuntimeError('Incomplete runtime: ' + str(required))
    if not shutil.which('docker'):
        raise RuntimeError('Docker CLI is not available in PATH.')


def run_service(service):
    preflight(service)
    if service != 'dashboard':
        container_info(start=True)
    lock_dir = ROOT / '.local/locks'
    lock_dir.mkdir(parents=True, exist_ok=True)
    with (lock_dir / (service + '.lock')).open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(service + ' already has a local launcher. No duplicate started.')
        if service_active(service):
            raise RuntimeError(service + ' is already active. No duplicate started or process stopped.')
        print('Working directory: ' + str(ROOT), flush=True)
        print('Service: ' + service + ' — Ctrl+C to stop this tab', flush=True)
        process = subprocess.Popen(command_for(service), cwd=ROOT)
        try:
            return process.wait()
        except KeyboardInterrupt:
            # Terminal sends SIGINT to the foreground process group, including the child.
            try:
                return process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                print('Stop still pending. No forced termination performed.', file=sys.stderr)
                return 130


def apple_string(value):
    return json.dumps(value, ensure_ascii=False)


def open_stack():
    preflight()
    container_info(start=True)
    # A .command document is executed, not pasted into an interactive prompt.
    # Open in the background so typing in the user's current app is unaffected.
    for service in SERVICES:
        if service_active(service):
            print(service + ': already active; no duplicate tab opened.')
            continue
        launcher = ROOT / 'scripts' / ('run_' + service + '.command')
        subprocess.run(['open', '-g', '-a', 'Terminal', str(launcher)], check=True)
    open_renderer()
    print('Dashboard: http://127.0.0.1:8766/#settings')
    print('No scenario or Play started. See docs/SESSION_LOCALE.md for the two-image pilot.')


def open_renderer():
    profile = engine_profile()
    print('Configured renderer: ' + profile['label'])
    if profile['id'] != 'unity':
        print('No editor was launched automatically. Use the selected adapter instructions or neutral scene contract.')
        return
    running = subprocess.run(['pgrep', '-x', 'Unity'], capture_output=True).returncode == 0
    if running:
        print('Unity is already open: not launching another editor. Check its project path.')
    elif UNITY_APP.is_dir():
        # Launching this Editor outside Hub fails named-user/Personal activation
        # on this Mac. Keep account authentication in the official Hub UI.
        subprocess.run(['open', '-a', 'Unity Hub'], check=True)
        print('In Unity Hub: Add project from disk -> ' + str(UNITY))
        print('Then open that exact project. No license tier is changed by this launcher.')
    else:
        print('Open runtime/LOTUSim-Unity-modules manually in Unity 2022.3.18f1.')


def status():
    preflight()
    info = container_info()
    print('Root: ' + str(ROOT))
    print('Container: ' + info['State']['Status'] + '; /workspace -> ' + str(CORE))
    for service in SERVICES:
        active = service_active(service) if info['State']['Running'] or service == 'dashboard' else False
        suffix = ' (localhost:' + str(PORTS[service]) + ')' if service in PORTS else ''
        print(service + suffix + ': ' + ('running' if active else 'stopped'))
    profile = engine_profile()
    print('Configured renderer: ' + profile['label'] + '; selecting a name does not execute or validate it')
    print('Legacy Unity editor: ' + ('open' if subprocess.run(['pgrep', '-x', 'Unity'], capture_output=True).returncode == 0 else 'closed'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('open', 'status', 'run'), nargs='?', default='open')
    parser.add_argument('service', choices=SERVICES, nargs='?')
    args = parser.parse_args()
    try:
        if args.action == 'run':
            if args.service is None:
                parser.error('run requires a service name')
            return run_service(args.service)
        if args.service:
            parser.error('a service is only accepted after run')
        if args.action == 'status':
            status()
        else:
            open_stack()
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print('Local stack: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
