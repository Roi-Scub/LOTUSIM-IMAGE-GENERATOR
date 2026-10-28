"""Optional bounded job telemetry; errors never alter simulation/planning work."""

from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

# Keep the optional probe independent of the simulation's subprocess runner.
# In particular, wrapping/mocking the worker launch must not launch an extra
# "worker" or change its expected argument contract merely for telemetry.
_PROCESS_RUN = subprocess.run


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def process_birth(pid=None):
    try:
        chosen = os.getpid() if pid is None else pid
        if isinstance(chosen, bool) or not isinstance(chosen, int) or chosen <= 0:
            return None
        result = _PROCESS_RUN(
            ['ps', '-p', str(chosen), '-o', 'lstart='],
            capture_output=True,
            text=True,
            timeout=0.5,
            check=False,
            env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LC_ALL': 'C'},
        )
        if result.returncode != 0 or not isinstance(result.stdout, str):
            return None
        return result.stdout.strip() or None
    except Exception:
        # Process inspection is optional, including malformed platform output
        # or instrumented subprocess adapters. Never turn it into a job error.
        return None


def safe_text(value, limit=240):
    return ' '.join(str(value or '').split())[:limit]


class OpsRuntime:
    def __init__(self, path, role, clock=time.monotonic):
        self.path = Path(path)
        self.role = role
        self.clock = clock
        self.events = deque(maxlen=200)
        self.count = 0
        self.next_write = 0
        self.record = {
            'schema': 'lotusim-ops-job-1',
            'pid': os.getpid(),
            'processBirth': process_birth(),
            'role': role,
            'state': 'running',
            'sessionId': uuid.uuid4().hex,
            'startedAt': now_iso(),
        }
        self.write(True)

    def write(self, force=False):
        try:
            at = self.clock()
            if not force and at < self.next_write:
                return False
            self.next_write = at + 0.2
            self.record['updatedAt'] = now_iso()
            self.record['eventCount'] = self.count
            self.record['events'] = list(self.events)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + '.partial')
            temporary.write_text(
                json.dumps(self.record, ensure_ascii=False, allow_nan=False), encoding='utf-8'
            )
            temporary.replace(self.path)
            return True
        except Exception:
            return False

    def update(self, state, **fields):
        self.record['state'] = state
        for key in ('currentAgent', 'phase', 'completed', 'expected', 'error'):
            if key in fields:
                self.record[key] = (
                    safe_text(fields[key]) if key not in ('completed', 'expected') else fields[key]
                )
        return self.write(True)

    def event(self, message):
        self.count += 1
        sender = safe_text(message.get('sender', message.get('agent')), 100)
        kind = safe_text(message.get('kind', message.get('state')), 100)
        actor = safe_text(message.get('actor'), 100)
        recipient = safe_text(message.get('recipient'), 100)
        event = {
            'id': self.record['sessionId'] + ':' + str(self.count),
            'at': now_iso(),
            'source': sender or self.role,
            'recipient': recipient,
            'kind': kind,
            'actor': actor,
            'message': sender
            + (' → ' + recipient if recipient else '')
            + ' · '
            + kind
            + (' · ' + actor if actor else ''),
        }
        self.events.append(event)
        self.record['currentAgent'] = sender
        self.record['phase'] = kind
        self.write()

    def complete(self):
        self.update('complete')

    def fail(self, error):
        self.update('failed', error=type(error).__name__ + ': ' + safe_text(error))
