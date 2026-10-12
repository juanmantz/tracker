import copy
import http.client
import json
import stat
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

from dreamstime.connection import DreamsConnection, ConnectionError
from dreamstime.core import Tracker, document_identity
from dreamstime.dreams import build_worked_batch
from dreamstime.recognition import recognize
from dreamstime.replay import BASE
from dreamstime.server import App, handler_for
from dreamstime.sync import DreamsSync
from tests.dreams_provider import Provider, map_fixture


class RecognitionTests(unittest.TestCase):
    def setUp(self):
        self.tracker = Tracker()
        self.tracker.import_projects(map_fixture())

    def tearDown(self):
        self.tracker.close()

    def sample(self, offset, title='Unrelated document', document='', **extra):
        self.tracker.ingest({'ts':BASE+offset, 'app':'com.figma.Desktop', 'app_name':'Figma', 'title':title, 'document':document, 'idle':0, **extra})

    def test_native_linked_file_survives_rename_and_corrections(self):
        url = 'https://www.figma.com/design/atlasFile/Renamed?secret=private#token'
        self.sample(0, document=url); self.sample(2, document=url)
        report = self.tracker.report('2026-10-05')
        self.assertEqual(report['totals'], {'atlas':2})
        self.assertNotIn('secret', json.dumps(report))
        self.tracker.add_rule('identity', 'figma:atlasFile', 'birch')
        self.assertEqual(self.tracker.report('2026-10-05')['totals'], {'birch':2})
        self.assertEqual(self.tracker.current['project'], 'birch')

    def test_document_names_and_paths_recognize_unique_projects(self):
        self.sample(0, title='Atlas Studio · Design'); self.sample(2, title='Atlas Studio · Design')
        self.assertEqual(self.tracker.current['project'], 'atlas')
        self.sample(4, title='Untitled', document='file:///Users/me/Birch%20Client/draft.ai')
        self.assertEqual(self.tracker.current['project'], 'birch')

    def test_conversation_mentions_suggest_without_assigning(self):
        self.sample(0, title='ChatGPT', desktop_context='Let us work on Atlas Studio branding')
        self.sample(2, title='ChatGPT', desktop_context='Let us work on Atlas Studio branding')
        segment = self.tracker.report('2026-10-05')['segments'][0]
        self.assertIsNone(segment['project'])
        self.assertEqual(segment['recognition']['candidates'][0]['project'], 'atlas')
        self.assertNotIn('Let us work', json.dumps(segment))

    def test_context_hint_cache_is_bounded_and_scoped_to_the_same_document(self):
        self.sample(0,title='Strategy',document='https://chatgpt.com/c/one',desktop_context='Atlas Studio')
        self.sample(2,title='Strategy',document='https://chatgpt.com/c/one')
        self.assertEqual(self.tracker.recommendation(self.tracker.current['context'])['confidence'],'suggested')
        self.sample(4,title='Strategy',document='https://chatgpt.com/c/two')
        self.assertEqual(self.tracker.recommendation(self.tracker.current['context'])['confidence'],'none')
        self.sample(14,title='Strategy',document='https://chatgpt.com/c/one')
        self.assertEqual(self.tracker.recommendation(self.tracker.current['context'])['confidence'],'none')

    def test_ambiguous_document_and_generic_names_never_auto_assign(self):
        catalog = [{'id':'a','name':'Atlas Studio','identities':['figma:x']}, {'id':'b','name':'Birch Client','identities':['figma:x']}]
        self.assertEqual(recognize({'identity':'figma:x'}, catalog)['confidence'], 'ambiguous')
        self.assertIsNone(recognize({'title':'Atlas Studio versus Birch Client'}, catalog)['project'])
        self.assertIsNone(recognize({'title':'Design'}, [{'id':'d','name':'Design'}])['project'])

    def test_narrow_name_wins_over_its_parent_name(self):
        catalog = [{'id':'a','name':'Atlas'}, {'id':'b','name':'Atlas Identity'}]
        self.assertEqual(recognize({'title':'Atlas Identity - Figma'}, catalog)['project'], 'b')

    def test_file_url_drops_credentials_and_query(self):
        self.assertEqual(document_identity('file://localhost/Projects/Atlas.ai?token=x'), ('file:///Projects/Atlas.ai','file:///Projects/Atlas.ai'))
        self.assertEqual(document_identity('file://remote/secret'), ('',''))

    def test_generic_activity_assignment_survives_catalog_refresh(self):
        self.sample(0,title='ChatGPT'); self.sample(2,title='ChatGPT')
        segment=self.tracker.report('2026-10-05')['segments'][0]
        self.tracker.assign_activity(segment['id'],'atlas')
        self.tracker.import_projects(map_fixture())
        self.assertEqual(self.tracker.report('2026-10-05')['totals'],{'atlas':2})
        self.sample(4,title='ChatGPT')
        self.assertIsNone(self.tracker.current['project'])


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.provider = Provider()
        self.app = App(self.directory.name, 0)
        self.server = ThreadingHTTPServer(('127.0.0.1',0), handler_for(self.app))
        self.app.port = self.server.server_port
        self.app.connection = DreamsConnection(self.directory.name, self.app.port, self.provider.origin)
        self.app.sync = DreamsSync(self.app.tracker, self.app.connection, self.app.installation)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close()
        self.provider.close(); self.app.tracker.close(); self.directory.cleanup()

    def api(self, path, data):
        connection = http.client.HTTPConnection('127.0.0.1', self.app.port, timeout=10)
        connection.request('POST',path,json.dumps(data),{'Content-Type':'application/json','Authorization':'Bearer '+self.app.token})
        response = connection.getresponse()
        status, body = response.status, json.loads(response.read())
        connection.close()
        return status, body

    def connect(self):
        status, body = self.api('/api/dreams/connect', {})
        self.assertEqual(status,200)
        # Real redirect through provider, PKCE exchange, local callback and project load.
        with urlopen(body['url']) as response:
            self.assertEqual(response.status,200)
            self.assertIn('#projects',response.url)
        self.assertEqual(len(self.app.tracker.projects()),2)

    def activity(self):
        for offset in range(0,62,2):
            self.app.tracker.ingest({'ts':BASE+offset,'idle':0,'app':'com.figma.Desktop','app_name':'Figma','title':'Renamed file','document':'https://figma.com/design/atlasFile/Unrelated'})

    def hours(self, target='atlas'):
        measurements = next(n['measurements'] for n in self.provider.map['nodes'] if n['id']==target)
        return [m['amount']['value'] for m in measurements]

    def test_real_http_oauth_recognition_sync_repeat_and_correction(self):
        self.connect(); self.activity()
        status, result = self.api('/api/dreams/sync', {'week':'2026-10-05'})
        self.assertEqual(status,200,result); self.assertEqual(result['seconds'],60)
        self.assertEqual(self.hours(),[round(60/3600,6)])
        status, result = self.api('/api/dreams/sync', {'week':'2026-10-05'})
        self.assertEqual(status,200); self.assertTrue(result['unchanged']); self.assertEqual(len(self.provider.writes),1)
        self.app.tracker.add_rule('identity','figma:atlasFile','birch')
        self.assertEqual(self.api('/api/dreams/sync', {'week':'2026-10-05'})[0],200)
        self.assertEqual(self.hours(),[0]); self.assertEqual(self.hours('birch'),[round(60/3600,6)])
        self.assertEqual(self.provider.writes[0]['commands'][0]['measurement']['id'],self.provider.writes[1]['commands'][0]['measurement']['id'])
        self.assertNotIn('Renamed file',json.dumps(self.provider.writes))

    def test_unknown_write_outcome_retries_identical_request_after_restart(self):
        self.connect(); self.activity(); self.provider.fail_after_write=True
        self.assertEqual(self.api('/api/dreams/sync', {'week':'2026-10-05'})[0],400)
        pending = self.app.tracker.setting('pending_sync')
        self.assertIsNotNone(pending)
        self.app.connection = DreamsConnection(self.directory.name,self.app.port,self.provider.origin)
        self.app.sync = DreamsSync(self.app.tracker,self.app.connection,self.app.installation)
        self.assertEqual(self.api('/api/dreams/sync', {'week':'2026-10-05'})[0],200)
        self.assertEqual(len(self.provider.writes),1)
        self.assertEqual(pending['batch']['requestId'],self.provider.writes[0]['requestId'])
        self.assertIsNone(self.app.tracker.setting('pending_sync'))

    def test_revision_conflict_preserves_hours_and_rebuilds_from_fresh_map(self):
        self.connect(); self.activity(); self.provider.force_conflict=True
        self.assertEqual(self.api('/api/dreams/sync', {'week':'2026-10-05'})[0],400)
        self.assertIsNone(self.app.tracker.setting('pending_sync'))
        self.provider.map['revision']+=1
        self.assertEqual(self.api('/api/dreams/sync', {'week':'2026-10-05'})[0],200)
        self.assertEqual(len(self.provider.writes),1)

    def test_refresh_rotation_private_credentials_and_disconnect(self):
        self.connect()
        old = self.app.connection.credentials['refresh_token']
        self.app.connection.credentials['expires_at']=0
        self.assertEqual(self.api('/api/dreams/refresh',{})[0],200)
        self.assertEqual(self.provider.refresh_count,1)
        self.assertNotEqual(old,self.app.connection.credentials['refresh_token'])
        self.assertEqual(stat.S_IMODE(self.app.connection.path.stat().st_mode),0o600)
        snapshot=json.dumps(self.app.snapshot())
        self.assertNotIn(self.app.connection.credentials['access_token'],snapshot)
        self.assertEqual(self.api('/api/dreams/disconnect',{})[0],200)
        self.assertFalse(self.app.connection.path.exists())
        self.assertEqual(self.app.tracker.report('2026-10-05')['total_seconds'],0)

    def test_callback_state_and_issuer_rejected_without_consuming_wrong_state(self):
        url=self.app.connection.begin(); state=parse_qs(urlsplit(url).query)['state'][0]
        with self.assertRaises(ConnectionError): self.app.connection.finish({'state':['bad'],'code':['bad'],'iss':[self.provider.origin]})
        self.assertIsNotNone(self.app.connection.pending)
        with self.assertRaises(ConnectionError): self.app.connection.finish({'state':[state],'code':['bad'],'iss':['https://attacker.example']})
        self.assertIsNone(self.app.connection.pending)

    def test_weekly_sync_only_completed_weeks_and_unknown_time_stays_local(self):
        self.connect(); self.activity()
        self.app.tracker.ingest({'ts':BASE+62,'idle':0,'app':'editor','title':'Untitled'})
        self.app.tracker.ingest({'ts':BASE+64,'idle':0,'app':'editor','title':'Untitled'})
        self.app.tracker.set_setting('weekly_sync',True)
        self.app.sync.weekly_tick(BASE+100)
        self.assertEqual(len(self.provider.writes),0)
        self.app.sync.weekly_tick(BASE+7*86400)
        self.assertEqual(len(self.provider.writes),1)
        self.assertEqual(self.app.tracker.report('2026-10-05')['totals']['unassigned'],2)
        self.app.sync.weekly_tick(BASE+7*86400)
        self.assertEqual(len(self.provider.writes),1)

    def test_batch_rejects_unlinked_or_archived_destinations(self):
        self.connect(); self.activity()
        report=self.app.tracker.report('2026-10-05'); report['reviewed']=True
        state=copy.deepcopy(self.provider.map); state['nodes'][0]['archived']=True
        with self.assertRaises(ValueError): build_worked_batch(report,state,self.app.installation)
        report['projects'][0]['dreams_id']=None
        with self.assertRaises(ValueError): build_worked_batch(report,self.provider.map,self.app.installation)

    def test_all_hours_reclassified_to_unknown_clear_own_snapshot(self):
        self.connect(); self.activity(); self.app.sync.send('2026-10-05')
        self.provider.map['nodes'][0]['fields']['links']=''
        self.app.sync.send('2026-10-05')
        self.assertEqual(self.hours(),[0])
        self.assertEqual(self.app.tracker.report('2026-10-05')['totals'],{'unassigned':60})

    def test_unchanged_response_checks_actual_remote_record_after_undo(self):
        self.connect(); self.activity(); self.app.sync.send('2026-10-05')
        self.provider.map['nodes'][0]['measurements']=[]
        self.provider.map['revision']+=1
        result=self.app.sync.send('2026-10-05')
        self.assertFalse(result.get('unchanged'))
        self.assertEqual(self.hours(),[round(60/3600,6)])
