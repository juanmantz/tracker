import unittest
from dreamstime.core import Tracker
from dreamstime.status import recording_status
from dreamstime.replay import BASE


class StatusTests(unittest.TestCase):
    def setUp(self): self.t = Tracker()
    def tearDown(self): self.t.close()
    def status(self, now=BASE+2, **kwargs):
        return recording_status(self.t, now, enabled=kwargs.get('enabled', True), running=kwargs.get('running', True), error=kwargs.get('error'), samples=kwargs.get('samples', 0))
    def sample(self, **kwargs):
        self.t.ingest({'ts':BASE, 'app':'editor', 'app_name':'Editor', 'idle':0, **kwargs})

    def test_capture_off_is_distinct_from_test_success(self):
        self.assertEqual(self.status(enabled=False, running=False)['state'], 'off')
        self.assertEqual(self.status(enabled=False, running=False)['today_seconds'], 0)

    def test_saved_seconds_and_fresh_process_prove_recording(self):
        self.sample(); self.t.ingest({'ts':BASE+2,'app':'editor'})
        status = self.status(samples=2)
        self.assertEqual(status['state'], 'recording')
        self.assertEqual(status['today_seconds'], 2)
        self.assertEqual(status['sample_count'], 2)

    def test_missing_permission_still_allows_app_level_time(self):
        self.sample(accessibility=False)
        self.assertEqual(self.status()['state'], 'recording')

    def test_browser_without_context_explains_zero_time(self):
        self.sample(app='com.google.Chrome')
        self.assertEqual(self.status()['state'], 'browser_unavailable')
        self.assertIn('companion', self.status()['detail'])

    def test_stopped_process_does_not_appear_to_be_recording(self):
        self.sample()
        self.assertEqual(self.status(running=False)['state'], 'failed')
        self.assertEqual(self.status(now=BASE+20)['state'], 'stale')

    def test_pause_idle_and_lock_are_distinct(self):
        self.sample(idle=130)
        self.assertEqual(self.status()['state'], 'idle')
        self.t.pause(True)
        self.assertEqual(self.status()['state'], 'paused')
        self.t.pause(False)
        self.sample(locked=True)
        self.assertEqual(self.status()['state'], 'locked')

    def test_native_error_is_not_silently_replaced_with_waiting(self):
        status = self.status(error='Mac capture stopped: execution error')
        self.assertEqual(status['state'], 'failed')
        self.assertIn('execution error', status['detail'])

if __name__ == '__main__': unittest.main()
