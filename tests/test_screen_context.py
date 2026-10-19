import json
import unittest
from dreamstime.core import Tracker, rememberable
from dreamstime.coordination import Coordination
from dreamstime.replay import BASE
from tests.dreams_provider import map_fixture
import tests.test_recognition_sync as integration


class ScreenEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.t=Tracker(); self.t.import_projects(map_fixture())
        self.t.set_setting('desktop_context_enabled',True)
    def tearDown(self): self.t.close()
    def sample(self,offset,text='Atlas Studio confidential conversation text',**extra):
        return self.t.ingest({'ts':BASE+offset,'app':'com.openai.chatgpt','app_name':'ChatGPT','title':'ChatGPT',
            'idle':0,'screen_capture_permission':True,'screen_context_at':BASE+offset,'screen_context':text,**extra})
    def test_screen_match_assigns_measured_seconds_without_retaining_image_or_transcript(self):
        self.sample(0);self.sample(2)
        self.assertEqual(self.t.report('2026-10-05')['totals'],{'atlas':2})
        self.assertFalse(rememberable(self.t.current['context']))
        self.assertIsNone(self.t.desktop_context)
        payload=Coordination(self.t,None,'mac').review_payload(BASE+2)
        body=json.dumps(payload)
        self.assertNotIn('confidential',body);self.assertNotIn('screen_context',body)
        self.assertIn('screen_ocr',body);self.assertIn('Atlas Studio',body)
        self.assertLess(payload['context_storage']['compressed_bytes'],512)
        self.assertFalse(payload['context_storage']['images_stored'])
    def test_ambiguous_or_missing_screen_names_remain_unassigned(self):
        self.sample(0,'Atlas Studio and Birch Client')
        self.assertIsNone(self.t.current['project'])
        self.sample(2,'No project in this work')
        self.assertIsNone(self.t.current['project'])
    def test_stale_future_denied_disabled_locked_and_browser_evidence_cannot_assign(self):
        for index,change in enumerate([{'screen_context_at':BASE-13},{'screen_context_at':BASE+3},
                       {'screen_capture_permission':False},{'locked':True},
                       {'app':'com.google.Chrome'},{'app':'com.1password.1password'}]):
            with self.subTest(change=change):
                self.sample(index*2,**change)
                self.assertIsNone(self.t.current['project'])
        self.t.set_setting('desktop_context_enabled',False)
        self.sample(20);self.assertIsNone(self.t.current['project'])
    def test_new_screen_evidence_changes_the_project_without_unbounded_learning(self):
        self.sample(0);self.sample(2)
        self.sample(4,'Birch Client');self.sample(6,'Birch Client')
        self.assertEqual(self.t.current['project'],'birch')
        self.sample(8,'Unrelated topic');self.assertIsNone(self.t.current['project'])

    def test_real_vision_output_with_cyrillic_digit_lookalike_matches_only_the_clear_project(self):
        self.t.import_projects({'revision':1,'nodes':[{'id':'fixture-'+str(i),'kind':'project',
            'name':'Fixture project '+str(i),'fields':{}} for i in range(11)],'edges':[]})
        self.sample(0,'7 Fixture project \u0417\nStoryboard work')
        self.assertEqual(self.t.current['project'],'fixture-3')
        self.sample(2,'Fixture project \u0417 and Fixture project 7')
        self.assertIsNone(self.t.current['project'])
        self.sample(4,'Unrelated work',title='Fixture project \u0417')
        self.assertIsNone(self.t.current['project'])


class ScreenTransferTests(unittest.TestCase):
    setUp=integration.IntegrationTests.setUp
    tearDown=integration.IntegrationTests.tearDown
    api=integration.IntegrationTests.api
    connect=integration.IntegrationTests.connect
    hours=integration.IntegrationTests.hours

    def test_screenshot_attribution_publishes_exactly_one_hour_with_readback_without_waiting(self):
        self.connect();self.app.tracker.set_setting('desktop_context_enabled',True)
        for offset in range(0,3601,10):
            self.app.tracker.ingest({'ts':BASE+offset,'idle':0,'app':'com.openai.chatgpt','app_name':'ChatGPT','title':'ChatGPT',
                'ax_trusted':False,'accessibility':False,'screen_capture_permission':True,
                'screen_context_at':BASE+offset,'screen_context':'Atlas Studio current design discussion'})
            if offset==3590:
                self.assertTrue(self.app.sync.send('2026-10-05')['skipped'])
                self.assertEqual(self.hours(),[])
        saved=self.app.sync.send('2026-10-05')
        self.assertEqual(saved['published_hours'],1)
        self.assertEqual(saved['verification'],'dreamstime/published/v1')
        self.assertEqual(self.hours(),[1]);self.assertEqual(self.hours('birch'),[])
        self.assertNotIn('current design discussion',json.dumps(self.provider.writes))
        self.app.sync.send('2026-10-05');self.assertEqual(len(self.provider.writes),1)
