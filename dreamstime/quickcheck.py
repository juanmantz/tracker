"""Observe the real sensor during a short guided check; never manufacture activity."""
import time


class QuickCheck:
    def __init__(self):
        self.started = None
        self.apps = set()
        self.samples = 0
        self.window_title = False
        self.last_at = None

    def start(self, now=None):
        self.started = time.time() if now is None else now
        self.apps.clear()
        self.samples = 0
        self.window_title = False
        self.last_at = None

    def observe(self, sample):
        if self.started is None or sample.get('ts', 0) < self.started:
            return
        self.samples += 1
        self.last_at = sample['ts']
        if sample.get('app') and not sample.get('locked'):
            self.apps.add(sample['app'])
        if sample.get('title') and sample.get('accessibility'):
            self.window_title = True

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        if self.started is None:
            return {'started': False, 'status': 'ready'}
        elapsed = max(0, now - self.started)
        connected = self.samples >= 2 and self.last_at is not None and 0 <= now - self.last_at <= 10
        switched = len(self.apps) >= 2
        checks = [
            {'name': 'Live samples arriving', 'passed': connected},
            {'name': 'Switch between two apps detected', 'passed': switched},
            {'name': 'Window title available', 'passed': self.window_title},
        ]
        passed = all(c['passed'] for c in checks)
        return {'started': True, 'elapsed_seconds': round(elapsed), 'samples': self.samples, 'checks': checks,
                'status': 'passed' if passed else 'needs_attention' if elapsed >= 30 else 'running'}
