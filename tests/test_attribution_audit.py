"""Regression: account-name pixels do not establish what work was performed."""
import json
import tempfile
import unittest
from pathlib import Path
from dreamstime.core import Tracker, context_key
from dreamstime.coordination import Coordination
from dreamstime.replay import BASE
from tests.dreams_provider import map_fixture
from tests import test_recognition_sync as integration

class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.t=Tracker();self.t.import_projects(map_fixture())
    def tearDown(self):self.t.close()
    def sample(self,at,**extra):
        self.t.ingest({'ts':BASE+at,'idle':0,'app':'com.openai.chatgpt','app_name':'ChatGPT','title':'ChatGPT',
            'screen_capture_permission':True,'screen_context_at':BASE+at,'screen_context':'Atlas Studio',**extra})
    def test_single_project_mention_cannot_assign_body_header_or_screenshot(self):
        for i,scope in enumerate(['screenshot','conversation','document_header','conversation_header']):
            self.sample(i*2,desktop_context='Atlas Studio',context_scope=scope)
            self.assertIsNone(self.t.current['project'])
            self.assertTrue(self.t.recommendation(self.t.current['context'])['candidates'])
    def test_account_name_title_is_not_a_document_and_specific_file_still_works(self):
        state=map_fixture();state['edges']=[{'source':'birch','target':'atlas','relation':'Part of'}]
        self.t.import_projects(state)
        self.sample(0,title='Atlas Studio',app='com.figma.Desktop',app_name='Figma')
        self.assertIsNone(self.t.current['project'])
        self.sample(2,title='Atlas Studio',app='com.openai.chatgpt')
        self.assertIsNone(self.t.current['project'])
        self.sample(4,title='Atlas Studio storyboard',app='com.figma.Desktop',app_name='Figma')
        self.assertIsNone(self.t.current['project'])
        self.t.set_setting('auto_associations',{context_key(self.t.current['context']):'atlas'})
        self.sample(5,title='Atlas Studio storyboard',app='com.figma.Desktop',app_name='Figma')
        self.assertEqual(self.t.current['project'],'atlas')
        self.sample(6,title='Renamed',document='https://figma.com/design/atlasFile/Actual')
        self.assertEqual(self.t.current['project'],'atlas')
    def test_audit_survives_full_uncertain_queue_and_reconciles_project_seconds(self):
        self.sample(0,title='Atlas Studio storyboard');self.sample(2,title='Atlas Studio storyboard')
        for i in range(2,450):self.sample(i*2,title='Unrelated discussion '+str(i),screen_context='Atlas Studio and Birch Client '+str(i))
        p=Coordination(self.t,None,'mac').review_payload(BASE+900)
        audit=p['assignment_audit'];row=next(x for x in audit['projects'] if x['project']=='atlas')
        self.assertEqual(row['seconds'],4)
        self.assertEqual(row['sources'][0]['title'],'Atlas Studio storyboard')
        self.assertEqual(sum(x['seconds'] for x in row['sources'])+row['omitted_seconds'],row['seconds'])
        self.assertLess(len(json.dumps(p,separators=(',',':'))),19000)
    def test_extreme_project_count_is_bounded_and_omissions_are_explicit(self):
        context={'app':'editor','app_name':'Editor','title':'Specific document','identity':'','url':''}
        for i in range(80):
            project='project-'+str(i)
            self.t.add_project(project,project)
            self.t.add_segment(BASE+i*2,BASE+i*2+1,context,project,'Manually assigned activity')
        payload=Coordination(self.t,None,'mac').review_payload(BASE+200)
        audit=payload['assignment_audit']
        self.assertEqual(audit['seconds'],80)
        self.assertGreater(audit['omitted_projects'],0)
        self.assertEqual(len(audit['projects'])+audit['omitted_projects'],80)
        self.assertLess(len(json.dumps(payload,separators=(',',':'))),19000)
    def test_upgrade_retracts_legacy_screen_assignment_without_losing_time_or_learned_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'activity.sqlite';old=Tracker(path);old.import_projects(map_fixture())
            context={'app':'com.openai.chatgpt','app_name':'ChatGPT','title':'ChatGPT','identity':'','url':'',
                'context_scope':'screenshot','project_hints':[{'project':'atlas'}]}
            old.add_segment(BASE,BASE+3600,context,'atlas','Project read from the active work window')
            file={'app':'com.figma.Desktop','app_name':'Figma','title':'Client layout','identity':'','url':''}
            old.set_setting('auto_associations',{context_key(file):'birch'})
            old.add_segment(BASE+3600,BASE+3660,file,'birch','Project learned from daily review')
            old.set_setting('attribution_policy','legacy');old.close()
            upgraded=Tracker(path)
            try:
                report=upgraded.report('2026-10-05')
                self.assertEqual(report['totals'],{'unassigned':3600,'birch':60})
                self.assertEqual(report['total_seconds'],3660)
                self.assertTrue(upgraded.setting('auto_dirty'))
            finally:upgraded.close()

class CorrectedPublicationTests(unittest.TestCase):
    setUp=integration.IntegrationTests.setUp
    tearDown=integration.IntegrationTests.tearDown
    connect=integration.IntegrationTests.connect
    api=integration.IntegrationTests.api
    hours=integration.IntegrationTests.hours
    def test_legacy_hour_is_replaced_by_zero_and_new_supported_hour_has_audit(self):
        self.connect()
        context={'app':'com.openai.chatgpt','app_name':'ChatGPT','title':'ChatGPT','identity':'','url':'',
                 'context_scope':'screenshot','project_hints':[{'project':'atlas'}]}
        self.app.tracker.add_segment(BASE,BASE+3600,context,'atlas','Project read from the active work window')
        # Emulate an existing legacy own-work record, then let the Mac correct it.
        self.app.sync.send('2026-10-05');self.assertEqual(self.hours(),[1])
        self.app.tracker.reclassify();self.app.sync.send('2026-10-05')
        self.assertEqual(self.hours(),[0])
        self.assertEqual(self.app.tracker.report('2026-10-05')['totals'],{'unassigned':3600})
        for offset in range(3600,7201,10):
            self.app.tracker.ingest({'ts':BASE+offset,'idle':0,'app':'com.figma.Desktop','app_name':'Figma',
                'title':'Brand storyboard','document':'https://figma.com/design/atlasFile/Brand'})
        saved=self.app.sync.send('2026-10-05');self.assertEqual(saved['published_hours'],1)
        self.assertEqual(self.hours(),[1]);self.assertEqual(saved['verification'],'dreamstime/published/v1')
        audit=Coordination(self.app.tracker,None,'mac').review_payload(BASE+7200)['assignment_audit']
        row=next(x for x in audit['projects'] if x['project']=='atlas')
        self.assertEqual(row['seconds'],3600);self.assertEqual(row['publishable_hours'],1)
        self.assertEqual(row['sources'][0]['title'],'Brand storyboard')
