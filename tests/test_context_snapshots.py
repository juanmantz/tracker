"""Accelerated context, storage and call timing tests; no account data."""
import json
import sqlite3
import unittest
import uuid
from dreamstime.context_snapshots import ContextSnapshots, compact_card, encoded, RETENTION_SECONDS
from dreamstime.core import Tracker, context_key, digest, rememberable
from dreamstime.coordination import Coordination
from dreamstime.replay import BASE
from dreamstime.status import recording_status
from tests.dreams_provider import map_fixture

def card(label='Atlas Studio',kind='document',scope='document_header'):
    return {'schema':'dreamstime/context/v1','kind':kind,'scope':scope,'labels':[label]}

class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.t=Tracker()
        self.t.import_projects(map_fixture())
    def tearDown(self):self.t.close()
    def sample(self,offset,**extra):
        self.t.ingest({'ts':BASE+offset,'mono':BASE+offset,'app':'com.openai.chat',
            'app_name':'ChatGPT','title':'ChatGPT','idle':0,**extra})
    def test_snapshot_is_small_redacted_and_deduplicated(self):
        raw=card('Atlas Studio https://user:secret@example.org/file?token=secret '+('🌳'*300))
        raw.update(transcript='PRIVATE WHOLE CONVERSATION',pixels='RAW IMAGE',keyboard='PASSWORD')
        for i in range(0,1200,2):self.sample(i,context_snapshot=raw)
        stats=self.t.context_snapshots.stats(BASE+1200)
        self.assertEqual(stats['cards'],1)
        self.assertLess(stats['compressed_bytes'],1024)
        saved=self.t.context_snapshots.get(self.t.current['context']['snapshot_id'])
        self.assertLessEqual(len(encoded(saved)),512)
        self.assertNotIn('secret',json.dumps(saved))
        self.assertNotIn('PRIVATE',json.dumps(saved))
        self.assertFalse(stats['images_stored'])
    def test_changed_generic_chat_context_is_bounded_not_a_global_association(self):
        self.sample(0,context_snapshot=card('Atlas Studio',kind='conversation',scope='conversation_header'))
        self.sample(2,context_snapshot=card('Atlas Studio',kind='conversation',scope='conversation_header'))
        first=context_key(self.t.current['context'])
        self.sample(4,context_snapshot=card('Birch Client',kind='conversation',scope='conversation_header'))
        second=context_key(self.t.current['context'])
        self.assertNotEqual(first,second)
        self.assertFalse(rememberable(self.t.current['context']))
        self.assertIsNone(self.t.current['project'])
        self.assertEqual(self.t.recommendation(self.t.current['context'])['candidates'][0]['project'],'birch')
        self.t.set_setting('auto_decisions',[{'context':first,'project':'atlas','start':BASE,'end':BASE+4}])
        self.t.reclassify()
        self.assertEqual(self.t.report('2026-10-05')['totals']['atlas'],4)
        self.assertIsNone(self.t.current['project'])
    def test_generic_chat_toolbar_is_not_promoted_to_current_conversation(self):
        self.sample(0,context_snapshot=card('Atlas Studio',scope='document_header'))
        self.assertIsNone(self.t.current['project'])
        self.assertFalse(rememberable(self.t.current['context']))
    def test_header_label_alone_does_not_prove_a_specific_file(self):
        self.sample(0,app='com.figma.Desktop',app_name='Figma',title='Untitled',context_snapshot=card('Atlas Studio'))
        self.assertIsNone(self.t.current['project'])
    def test_window_metadata_keeps_preupgrade_specific_file_keys(self):
        self.sample(0,app='com.figma.Desktop',app_name='Figma',title='Client storyboard')
        before=context_key(self.t.current['context'])
        self.sample(2,app='com.figma.Desktop',app_name='Figma',title='Client storyboard',
                    context_snapshot=card('Client storyboard',kind='window',scope='window_metadata'))
        self.assertEqual(context_key(self.t.current['context']),before)
    def test_legacy_context_keys_and_specific_file_associations_survive(self):
        old={'app':'com.figma.Desktop','identity':'','title':'Draft'}
        self.assertEqual(context_key(old),digest(['com.figma.Desktop','','Draft',[]]))
        file={'app':'com.figma.Desktop','identity':'figma:key','title':'Draft'}
        self.assertEqual(context_key(file),context_key({**file,'snapshot_id':'different','title':'Renamed'}))
    def test_caps_retention_and_corrupt_evidence_do_not_destroy_measured_time(self):
        self.t.context_snapshots=ContextSnapshots(self.t.db,max_bytes=700,max_cards=3)
        for i in range(30):self.sample(i*2,context_snapshot=card('Document '+str(i)))
        stats=self.t.context_snapshots.stats(BASE+60)
        self.assertLessEqual(stats['cards'],3)
        self.assertLessEqual(stats['compressed_bytes'],700)
        self.assertEqual(self.t.report('2026-10-05')['total_seconds'],58)
        stats=self.t.context_snapshots.stats(BASE+60+RETENTION_SECONDS)
        self.assertEqual(stats['cards'],0)
        self.assertEqual(self.t.report('2026-10-05')['total_seconds'],58)
    def test_pause_lock_excluded_apps_and_opt_out_never_retain_snapshots(self):
        self.t.pause(True);self.sample(0,context_snapshot=card())
        self.t.pause(False);self.sample(2,locked=True,context_snapshot=card())
        self.sample(4,app='com.1password.1password',context_snapshot=card())
        self.t.set_setting('desktop_context_enabled',False)
        self.sample(6,context_snapshot=card())
        self.assertEqual(self.t.context_snapshots.stats(BASE+6)['cards'],0)
    def test_compact_review_prioritizes_call_evidence_and_exposes_coverage(self):
        for i in range(220):self.sample(i*4,title='Inbox unread '+str(i))
        self.sample(900,app='net.whatsapp.WhatsApp',title='Podcast partner - video call',
                    call_active=True,call_session=str(uuid.uuid4()),call_verified_at=BASE+900,
                    call_proof='end-control+duration',ax_trusted=True,window_access_status='readable',
                    context_snapshot={**card('Podcast partner','call','call_controls'),'state':'connected'})
        self.sample(902)
        call_segment=self.t.report('2026-10-05')['segments'][-1]
        self.t.assign_activity(call_segment['id'],'atlas')
        payload=Coordination(self.t,None,'fixture').review_payload(BASE+904)
        self.assertLessEqual(len(json.dumps(payload,separators=(',',':'))),18000)
        self.assertEqual(payload['activities'][0]['kind'],'call')
        self.assertIn(payload['activities'][0]['snapshot'],payload['snapshots'])
        self.assertFalse(payload['activities'][0]['can_remember'])
        self.assertGreater(payload['omitted_groups'],0)
        self.assertGreater(payload['omitted_seconds'],0)

class CallTests(unittest.TestCase):
    def setUp(self):
        self.t=Tracker()
        self.t.import_projects(map_fixture())
        self.session=str(uuid.uuid4())
    def tearDown(self):self.t.close()
    def sample(self,offset,**extra):
        self.t.ingest({'ts':BASE+offset,'mono':BASE+offset,'idle':1200+offset,
            'app':'net.whatsapp.WhatsApp','app_name':'WhatsApp',
            'title':'Podcast partner - WhatsApp video call','ax_trusted':True,
            'window_access_status':'readable','call_active':True,'call_session':self.session,
            'call_verified_at':BASE+offset,'call_proof':'end-control+duration',**extra})
    def test_listening_time_survives_idle_and_is_not_deleted_when_call_ends(self):
        for i in range(0,600,2):self.sample(i)
        self.sample(600,call_active=False,app='editor')
        self.sample(602,call_active=False,app='editor')
        self.assertEqual(self.t.report('2026-10-05')['total_seconds'],600)
        self.assertTrue(all(not rememberable(s['context']) for s in self.t.report('2026-10-05')['segments']))
    def test_call_is_counted_once_and_project_correction_cannot_touch_other_calls(self):
        for i in range(0,60,2):self.sample(i)
        first=context_key(self.t.current['context'])
        self.t.set_setting('auto_decisions',[{'context':first,'project':'atlas','start':BASE,'end':BASE+60}])
        self.t.reclassify()
        self.session=str(uuid.uuid4())
        self.sample(60);self.sample(62)
        self.assertIsNone(self.t.current['project'])
        report=self.t.report('2026-10-05')
        self.assertEqual(report['total_seconds'],62)
        self.assertEqual(report['totals']['atlas'],60)
        self.assertEqual(report['totals']['unassigned'],2)
        for a,b in zip(report['segments'],report['segments'][1:]):self.assertLessEqual(a['end'],b['start'])
    def test_stale_or_missing_controls_do_not_override_idle(self):
        for overrides in ({'call_verified_at':BASE-20},{'call_active':False},
                          {'call_proof':'title only'},{'ax_trusted':False},
                          {'app':'com.openai.chat'}):
            self.t.previous=None
            self.sample(0,**overrides);self.sample(2,**overrides)
            self.assertEqual(self.t.report('2026-10-05')['total_seconds'],0)
    def test_pause_lock_and_sleep_gap_stop_calls_without_backfill(self):
        self.sample(0);self.sample(2);self.sample(4,locked=True)
        self.sample(6,locked=True);self.sample(3606);self.sample(3608)
        self.assertEqual(self.t.report('2026-10-05')['total_seconds'],4)
        self.t.pause(True);self.sample(3610);self.sample(3612)
        self.assertEqual(self.t.report('2026-10-05')['total_seconds'],4)
    def test_live_call_status_does_not_claim_the_listener_is_idle(self):
        self.sample(0);self.sample(2)
        status=recording_status(self.t,BASE+2,enabled=True,running=True)
        self.assertEqual(status['state'],'recording')
        self.assertIn('listening',status['detail'])

if __name__=='__main__':unittest.main()

class ReviewCoverageTests(unittest.TestCase):
    def test_inbox_counters_are_summarized_without_crowding_out_a_specific_file(self):
        t=Tracker();t.import_projects(map_fixture())
        try:
            for i in range(220):
                for dt in (0,2):
                    t.ingest({'ts':BASE+i*4+dt,'idle':0,'app':'com.apple.mail','app_name':'Mail',
                              'title':'All Inboxes – All Mail · '+str(i)+' unread'})
            for offset in (882,884):
                t.ingest({'ts':BASE+offset,'idle':0,'app':'com.figma.Desktop','app_name':'Figma',
                          'title':'Specific client proposal','document':'https://figma.com/design/newFile/Proposal'})
            payload=Coordination(t,None,'mac').review_payload(BASE+886)
            self.assertEqual(len(payload['activities']),1)
            self.assertEqual(payload['activities'][0]['title'],'Specific client proposal')
            self.assertEqual(payload['unattributed_summary'][0]['app'],'Mail')
            self.assertEqual(payload['summarized_groups'],220)
            self.assertEqual(payload['omitted_groups'],220)
            self.assertEqual(sum(r['seconds'] for r in payload['activities'])+payload['omitted_seconds'],
                             t.report('2026-10-05')['total_seconds'])
            self.assertLess(len(json.dumps(payload,separators=(',',':'))),18000)
        finally:t.close()

    def test_unicode_summary_still_fits_field_limit_and_reports_partial_coverage(self):
        t=Tracker()
        try:
            for i in range(100):
                for dt in (0,2):
                    t.ingest({'ts':BASE+i*4+dt,'idle':0,'app':'app'+str(i),
                              'app_name':str(i)+'🌳'*100,'title':''})
            payload=Coordination(t,None,'mac').review_payload(BASE+402)
            self.assertLess(len(json.dumps(payload,separators=(',',':'))),18000)
            self.assertGreater(payload['summary_omitted_groups'],0)
            self.assertEqual(payload['omitted_groups'],100)
        finally:t.close()
