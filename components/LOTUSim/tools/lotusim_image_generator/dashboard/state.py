"""Thread-safe cached monitoring state; no HTTP or scenario commands."""

import copy
from datetime import datetime, timezone
import json
import threading
import time


def iso_now():
    return datetime.now(timezone.utc).isoformat()


class StateHub:
    def __init__(self, collector, interval=2.0):
        self.collector = collector
        self.interval = interval
        self.condition = threading.Condition()
        self.stopped = threading.Event()
        self.version = 0
        self.error = None
        self.thread = None
        self.state = {
            'schema': 'lotusim-ops-state-1',
            'generatedAt': iso_now(),
            'health': {'state': 'unknown', 'detail': 'Démarrage du collecteur local'},
            'services': [],
            'agents': [],
            'events': [],
            'campaigns': [],
            'reports': [],
            'unity': None,
            'preview': None,
            'capture': None,
            'vision': None,
            'scene': None,
        }

    def refresh(self):
        try:
            state = self.collector.snapshot()
            json.dumps(state, allow_nan=False)
            self.error = None
        except Exception as error:
            state = copy.deepcopy(self.state)
            self.error = type(error).__name__
            state['health'] = {
                'state': 'error',
                'detail': 'Collecte indisponible ; dernier état conservé',
                'errorType': self.error,
            }
            for service in state.get('services', []):
                service['state'] = 'unknown'
            for agent in state.get('agents', []):
                agent['state'] = 'unknown'
            if isinstance(state.get('preview'), dict):
                state['preview']['live'] = False
        state['monitor'] = {
            'updatedAt': iso_now(),
            'intervalSeconds': self.interval,
            'readOnly': True,
            'collectorError': self.error,
        }
        with self.condition:
            self.state = state
            self.version += 1
            self.condition.notify_all()
        return state

    def start(self):
        def loop():
            while not self.stopped.is_set():
                started = time.monotonic()
                self.refresh()
                self.stopped.wait(max(0.05, self.interval - (time.monotonic() - started)))

        self.thread = threading.Thread(target=loop, name='lotusim-ops-collector', daemon=True)
        self.thread.start()

    def current(self):
        with self.condition:
            return self.version, copy.deepcopy(self.state)

    def close(self):
        self.stopped.set()
        with self.condition:
            self.condition.notify_all()
        if self.thread:
            self.thread.join(timeout=2)
