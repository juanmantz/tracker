import unittest
import uuid
from dreamstime.core import Tracker, context_key
from dreamstime.coordination import Coordination
from dreamstime.replay import BASE
from tests.dreams_provider import map_fixture
import json

class AutomaticContextEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.t=Tracker();self.t.import_projects(map_fixture());self.t.set_setting('desktop_context_enabled',True)
    def tearDown(self):self.t.close()
    def sample(self,offset,**extra):
        self.t.ingest({'ts':BASE+offset,'mono':BASE+offset,'idle':0,'app':'com.figma.Desktop',
            'app_name':'Figma','title':'Client storyboard','accessibility':True,**extra})
    def control(self,hints):
        policy={'schema':'dreamstime/control/v1','review_hints':hints}
        Coordination(self.t,None,'mac').consume({'nodes':[{'kind':'note','fields':{'notes':json.dumps(policy)}}]})
    def test_metadata_preserves_an_existing_file_association(self):
        self.sample(0);key=context_key(self.t.current['context'])
        self.t.set_setting('auto_associations',{key:'atlas'})
        self.sample(2,context_snapshot={'schema':'dreamstime/context/v1','kind':'window','scope':'window_metadata','labels':['Client storyboard']})
        self.assertEqual(context_key(self.t.current['context']),key)
        self.assertEqual(self.t.current['project'],'atlas')
    def test_only_a_connected_call_can_use_owner_confirmed_collaborator_context(self):
        self.control([{'kind':'collaborator','label':'Fixture Partner','project':'atlas','requires_session_evidence':True}])
        common={'app':'net.whatsapp.WhatsApp','app_name':'WhatsApp','title':'Fixture Partner - video call'}
        self.sample(0,**common);self.assertIsNone(self.t.current['project'])
        proof={**common,'call_active':True,'call_session':str(uuid.uuid4()),'call_verified_at':BASE+2,
            'call_proof':'end-control+duration','ax_trusted':True,'window_access_status':'readable'}
        self.sample(2,**proof);self.assertEqual(self.t.current['project'],'atlas')
        self.sample(4,app='com.openai.chat',app_name='ChatGPT',title='Chat with Fixture Partner')
        self.assertIsNone(self.t.current['project'])
    def test_ambiguous_collaborator_is_preserved_without_guessing(self):
        self.control([{'kind':'collaborator','label':'Fixture Partner','project':p,'requires_session_evidence':True} for p in ('atlas','birch')])
        self.sample(0,app='net.whatsapp.WhatsApp',app_name='WhatsApp',title='Fixture Partner - video call',
            call_active=True,call_session=str(uuid.uuid4()),call_verified_at=BASE,
            call_proof='end-control+duration',ax_trusted=True,window_access_status='readable')
        self.assertIsNone(self.t.current['project'])
    def test_noise_does_not_create_successful_context_cards(self):
        self.sample(0,app='local.dreamstime.companion',app_name='Dreams Time',title='Projects',
            context_snapshot={'schema':'dreamstime/context/v1','kind':'window','scope':'window_metadata','labels':['Projects']})
        self.assertEqual(self.t.context_snapshots.stats(BASE)['cards'],0)
    def test_capture_setting_and_native_capture_state_are_visible_without_raw_content(self):
        self.sample(0,context_enabled=True,context_capture_state='no_specific_context')
        report=Coordination(self.t,None,'mac').review_payload(BASE+1)
        self.assertTrue(report['context_capture_enabled'])
        self.assertEqual(report['sensor']['collector']['context_capture_state'],'no_specific_context')
        self.assertNotIn('desktop_context',report)
