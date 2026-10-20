import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from dreamstime.server import App
from dreamstime.coordination import Coordination

class NativeHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        with patch.dict(os.environ, {'DREAMSTIME_NATIVE_HOST': '1'}):
            self.app = App(self.temp.name)
    def tearDown(self):
        self.app.tracker.close()
        self.temp.cleanup()
    def sample(self, **updates):
        value = {'ts': time.time(), 'mono': time.monotonic(), 'idle': 0,
                 'app': 'com.figma.Desktop', 'app_name': 'Figma', 'title': 'Hey, transform',
                 'locked': False, 'accessibility': True, 'ax_trusted': True,
                 'collector_bundle': 'local.dreamstime.companion', 'collector_pid': 123,
                 'window_access_status': 'readable'}
        value.update(updates)
        return value
    def test_packaged_capture_does_not_spawn_a_separate_permission_identity(self):
        with patch('dreamstime.server.subprocess.Popen') as spawn:
            self.app.start_sensor()
            self.app.watchdog_tick()
            spawn.assert_not_called()
        self.assertIsNone(self.app.sensor)
    def test_real_app_samples_feed_existing_attribution_and_report_identity(self):
        self.app.tracker.import_projects({'revision':1,'nodes':[{'id':'hey','name':'Hey, transform','kind':'project','fields':{}}],'edges':[]})
        self.app.accept_native_sample(self.sample())
        report = Coordination(self.app.tracker, None, 'mac').review_payload(time.time())
        self.assertEqual(report['sensor']['collector']['collector_bundle'], 'local.dreamstime.companion')
        self.assertEqual(report['sensor']['collector']['window_access_status'], 'readable')
        self.assertTrue(self.app.snapshot()['recording']['process_running'])
        self.assertEqual(self.app.sample_count, 1)
        self.assertEqual(self.app.tracker.current["project"], "hey")
    def test_permission_probe_is_reported_separately_from_window_read(self):
        self.app.accept_native_sample(self.sample(accessibility=False, ax_trusted=False, window_access_status='ax_error_-25211'))
        collector = self.app.snapshot()['health']['collector']
        self.assertFalse(collector['ax_trusted'])
        self.assertEqual(collector['window_access_status'], 'ax_error_-25211')
    def test_reading_our_own_window_does_not_prove_external_document_access(self):
        self.app.start_sensor()
        self.app.accept_native_sample(self.sample(app='local.dreamstime.companion',app_name='Dreams Time',
            title='Dreams Time',accessibility=True,ax_trusted=False,window_access_status='readable'))
        snapshot=self.app.snapshot()
        self.assertFalse(snapshot['health']['accessibility'])
        self.assertEqual(snapshot['recording']['project_detection'],'permission_required')
        self.assertEqual(snapshot['recording']['state'],'permission_required')

    def test_legacy_or_stale_collector_cannot_submit_as_the_current_app(self):
        for sample in [self.sample(collector_bundle='local.dreamstime.sensor'), self.sample(ts=time.time()-60)]:
            with self.assertRaises(ValueError): self.app.accept_native_sample(sample)
        self.assertEqual(self.app.sample_count, 0)
    def test_pause_keeps_time_and_content_out_and_resume_is_automatic(self):
        self.app.tracker.pause(True)
        self.assertTrue(self.app.accept_native_sample(self.sample())['paused'])
        self.assertIsNone(self.app.tracker.health['last_sample'])
        self.app.tracker.pause(False)
        self.assertFalse(self.app.accept_native_sample({'heartbeat':True})['paused'])
        self.app.accept_native_sample(self.sample())
        self.assertEqual(self.app.sample_count,1)

    def test_screen_context_can_identify_work_when_accessibility_is_denied(self):
        self.app.tracker.import_projects({'revision':1,'nodes':[{'id':'hey','name':'Hey, transform','kind':'project','fields':{}}],'edges':[]})
        self.app.tracker.set_setting('desktop_context_enabled',True)
        self.app.start_sensor()
        self.app.accept_native_sample(self.sample(app='com.openai.chatgpt',title='ChatGPT',
            accessibility=False,ax_trusted=False,window_access_status='ax_error_-25211',
            context_enabled=True,screen_capture_permission=True,screen_capture_state='readable',
            screen_context_at=time.time(),screen_context='Hey, transform'))
        snap=self.app.snapshot()
        self.assertIsNone(snap['current']['project'])
        self.assertEqual(snap['recommendation']['candidates'][0]['project'],'hey')
        self.assertEqual(snap['recording']['project_detection'],'screen_ocr')
        self.assertNotEqual(snap['recording']['state'],'permission_required')
