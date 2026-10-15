"""Unattended work, recovery and daily review through a real HTTP OAuth provider."""
import copy
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from dreamstime.connection import DreamsConnection
from dreamstime.coordination import CONTROL_SCHEMA, REVIEW_SCHEMA, note_payload
from dreamstime.core import Tracker, context_key
from dreamstime.replay import BASE
from dreamstime.server import App
from dreamstime.sync import DreamsSync
from tests import test_recognition_sync as integration


class AutomaticTests(unittest.TestCase):
    setUp = integration.IntegrationTests.setUp
    tearDown = integration.IntegrationTests.tearDown
    api = integration.IntegrationTests.api
    connect = integration.IntegrationTests.connect
    hours = integration.IntegrationTests.hours

    def control(self, **changes):
        node = next((n for n in self.provider.map['nodes'] if n['id'] == 'control'), None)
        if node is None:
            node = {'id': 'control', 'kind': 'note', 'name': 'Dreams Time control', 'archived': True,
                    'fields': {'notes': json.dumps({'schema': CONTROL_SCHEMA, 'decisions': []})}}
            self.provider.map['nodes'].append(node)
        value = json.loads(node['fields']['notes'])
        value.update(changes)
        node['fields']['notes'] = json.dumps(value)
        self.provider.map['revision'] += 1

    def samples(self, start, end, **extra):
        for offset in range(start, end + 1, 2):
            self.app.tracker.ingest({'ts': BASE + offset, 'mono': BASE + offset, 'idle': 0,
                'app': 'com.openai.chat', 'app_name': 'ChatGPT', 'title': 'ChatGPT',
                'accessibility': True, 'mouse_idle': 0, 'keyboard_idle': 300, **extra})

    def tick(self, offset):
        self.app.sync.automatic_tick(BASE + offset)

    def test_collector_change_publishes_without_waiting_fifteen_minutes(self):
        self.connect()
        self.tick(0)
        first = self.app.tracker.setting('last_heartbeat')
        self.app.tracker.health.update(sensor='connected', accessibility=True,
            collector={'collector_bundle':'local.dreamstime.companion','collector_pid':123,'ax_trusted':True})
        self.tick(60)
        self.assertEqual(self.app.tracker.setting('last_heartbeat'), BASE+60)
        self.assertGreater(self.app.tracker.setting('last_heartbeat'), first)
        report = next(json.loads(n['fields']['notes']) for n in self.provider.map['nodes']
                      if n.get('kind')=='note' and json.loads(n['fields'].get('notes','{}')).get('schema')==REVIEW_SCHEMA)
        self.assertEqual(report['sensor']['collector']['collector_bundle'],'local.dreamstime.companion')
        self.tick(120)
        self.assertEqual(self.app.tracker.setting('last_heartbeat'), BASE+60)

    def test_unattended_eight_hour_day_project_changes_idle_offline_and_daily_correction(self):
        self.connect()
        self.control(focus={'project': 'atlas', 'at': BASE})
        self.tick(0)
        # Two hours of mouse-only use; no manual tracker assignment or sync calls.
        self.samples(0, 7200)
        self.tick(7200)
        self.assertEqual(self.hours('atlas'), [2])  # current week, immediately
        # ChatGPT changes the project at 11:00. The file identity still wins.
        self.control(focus={'project': 'birch', 'at': BASE + 7200})
        self.tick(7202)
        self.samples(7202, 10800)
        self.samples(10802, 14400, app='com.figma.Desktop', app_name='Figma',
                     title='Renamed', document='https://figma.com/design/atlasFile/private?token=secret')
        # Lunch: the complete idle tail, including provisional grace, is removed.
        for offset in range(14402, 18002, 2):
            self.samples(offset, offset, idle=offset-14400)
        self.samples(18002, 21600)
        self.provider.denied_path = '/mcp'
        with self.assertRaises(ValueError): self.tick(21600)
        self.assertIsNotNone(self.app.tracker.setting('auto_error_since'))
        # Independent measured activity in an unrelated app stays uncertain.
        self.samples(21602, 25200, app='example.editor', app_name='Editor', title='Draft for client')
        self.provider.denied_path = None
        # Response loss after a committed write: retry is byte-identical after restart.
        self.provider.fail_after_write = True
        with self.assertRaises(ValueError): self.tick(25200)
        pending = copy.deepcopy(self.app.tracker.setting('pending_sync'))
        self.assertIsNotNone(pending)
        self.app.connection = DreamsConnection(self.directory.name, self.app.port, self.provider.origin)
        self.app.sync = DreamsSync(self.app.tracker, self.app.connection, self.app.installation)
        self.tick(25202)
        self.assertIsNone(self.app.tracker.setting('pending_sync'))
        self.assertEqual(sum(w['requestId'] == pending['batch']['requestId'] for w in self.provider.writes), 1)
        self.samples(25202, 28800)
        before = self.app.tracker.report('2026-10-05')['total_seconds']
        self.tick(28800)
        review = next(note_payload(n, REVIEW_SCHEMA) for n in self.provider.map['nodes'] if note_payload(n, REVIEW_SCHEMA))
        unknown = [r for r in review['activities'] if r['project'] is None]
        self.assertTrue(unknown)
        # A daily ChatGPT review corrects only measured ranges; no synthetic time.
        self.control(decisions=[{'context': r['context'], 'project': 'birch', 'start': r['start'], 'end': r['end']} for r in unknown], reviewed_at=BASE+28800)
        self.tick(28802)
        report = self.app.tracker.report('2026-10-05')
        self.assertEqual(report['total_seconds'], before)
        self.assertEqual(before, 25198)  # eight hours minus lunch and two-second resume boundary
        self.assertEqual(report['totals'].get('unassigned', 0), 0)
        self.assertEqual(self.hours('atlas'), [round(report['totals']['atlas']/3600, 6)])
        self.assertEqual(self.hours('birch'), [round(report['totals']['birch']/3600, 6)])
        self.assertAlmostEqual(sum(self.hours('atlas')+self.hours('birch')), before/3600, places=5)
        writes = len(self.provider.writes)
        self.tick(29100)
        self.assertEqual(len(self.provider.writes), writes)  # unchanged totals: no duplicate hours
        self.assertNotIn('token=secret', json.dumps(review))
        self.assertTrue(next(n for n in self.provider.map['nodes'] if note_payload(n, REVIEW_SCHEMA))['archived'])

    def test_focus_history_splits_existing_intervals_without_reassigning_earlier_work(self):
        self.connect()
        self.samples(0, 120)
        self.control(focus={'project': 'atlas', 'at': BASE+30})
        self.tick(120)
        self.control(focus={'project': 'birch', 'at': BASE+60})
        self.tick(180)
        self.assertEqual(self.app.tracker.report('2026-10-05')['totals'], {'unassigned':30, 'atlas':30, 'birch':60})
        self.control(focus={'project': None, 'at': BASE+180})
        self.tick(182)
        self.samples(182, 184)
        self.assertIsNone(self.app.tracker.current['project'])

    def test_bounded_review_does_not_turn_generic_chatgpt_into_a_global_rule(self):
        self.connect(); self.samples(0, 120)
        key = context_key(self.app.tracker.current['context'])
        self.control(decisions=[{'context':key,'project':'birch','start':BASE+30,'end':BASE+60}])
        self.tick(120)
        self.assertEqual(self.app.tracker.report('2026-10-05')['totals'], {'unassigned':90,'birch':30})
        self.control(decisions=[]); self.tick(180)
        self.assertEqual(self.app.tracker.report('2026-10-05')['totals']['birch'],30)
        self.samples(182,184); self.assertIsNone(self.app.tracker.current['project'])

    def test_excluded_activity_never_inherits_focus_and_only_scoped_text_assigns(self):
        self.connect(); self.control(focus={'project':'atlas','at':BASE}); self.tick(0)
        self.samples(0,2,app='com.1password.1password')
        self.assertIsNone(self.app.tracker.current['project'])
        self.control(focus={'project':None,'at':BASE+2}); self.tick(2)
        self.samples(4,6,desktop_context='Birch Client conversation',context_scope='window')
        self.assertIsNone(self.app.tracker.current['project'])
        self.samples(8,10,desktop_context='Birch Client conversation',context_scope='conversation')
        self.assertEqual(self.app.tracker.current['project'],'birch')
        self.assertNotIn('conversation', json.dumps(self.app.tracker.current['context'].get('project_hints')))

    def test_unknown_note_write_is_retried_once_and_control_not_overwritten(self):
        self.connect(); self.control(focus={'project':'atlas','at':BASE})
        self.provider.fail_after_write = True
        with self.assertRaises(ValueError): self.tick(0)
        self.assertIsNotNone(self.app.tracker.setting('pending_coordination'))
        self.tick(60)
        notes = [n for n in self.provider.map['nodes'] if note_payload(n, REVIEW_SCHEMA)]
        self.assertEqual(len(notes),1)
        self.assertTrue(notes[0]['archived'])
        self.assertEqual(json.loads(next(n for n in self.provider.map['nodes'] if n['id']=='control')['fields']['notes'])['focus']['project'],'atlas')

    def test_disabled_automation_preserves_hours_without_remote_writes(self):
        self.connect(); self.samples(0,60,title='Atlas Studio')
        self.app.tracker.set_setting('automatic_sync',False); self.tick(300)
        self.assertEqual(self.provider.writes,[])
        self.assertEqual(self.app.tracker.report('2026-10-05')['total_seconds'],60)

    def test_learned_file_survives_rename_and_cannot_assign_generic_chats(self):
        self.connect()
        self.samples(0,60,app='com.figma.Desktop',title='Draft',document='https://figma.com/design/newFile/Draft')
        key = context_key(self.app.tracker.current['context'])
        self.control(associations=[{'context':key,'project':'birch'}]); self.tick(60)
        self.samples(62,64,app='com.figma.Desktop',title='Renamed',document='https://figma.com/design/newFile/Renamed')
        self.assertEqual(self.app.tracker.current['project'],'birch')
        self.samples(66,68)
        key = context_key(self.app.tracker.current['context'])
        self.control(associations=[{'context':key,'project':'atlas'}]); self.tick(68)
        self.assertIsNone(self.app.tracker.current['project'])

    def test_bad_remote_fields_do_not_crash_or_reassign_activity(self):
        self.connect(); self.samples(0,60)
        self.control(focus={'at':float('nan'),'project':'atlas'},
            associations=[None,{'context':123,'project':'atlas'}],
            decisions=[{'context':context_key(self.app.tracker.current['context']),'project':'atlas','start':BASE,'end':BASE+20*86400}])
        self.tick(60)
        self.assertEqual(self.app.tracker.report('2026-10-05')['totals'],{'unassigned':60})

    def test_busy_day_summary_stays_under_live_dreams_field_limit(self):
        self.connect()
        for i in range(200):
            self.samples(i*4,i*4+2,title=('Document '+str(i)+' x'*100))
        self.tick(900)
        review = next(note_payload(n, REVIEW_SCHEMA) for n in self.provider.map['nodes'] if note_payload(n, REVIEW_SCHEMA))
        self.assertLessEqual(len(json.dumps(review, separators=(',',':'))),18000)
        self.assertGreater(review['omitted_groups'],0)

    def test_archived_project_does_not_block_saving_other_current_work(self):
        self.connect(); self.samples(0,60,title='Atlas Studio'); self.tick(60)
        self.provider.map['nodes'][0]['archived'] = True
        self.provider.map['revision'] += 1
        self.samples(62,120,title='Birch Client'); self.tick(360)
        self.assertEqual(self.hours('birch'),[round(58/3600,6)])
        self.assertIsNone(self.app.tracker.setting('sync_error'))


class RecoveryTests(unittest.TestCase):
    def test_sensor_recovers_without_bridging_gap_but_respects_pause_and_quit(self):
        with tempfile.TemporaryDirectory() as directory:
            app = App(directory)
            app.tracker.set_setting('capture_enabled', True)
            app.sensor = Mock(); app.sensor.poll.return_value = 1
            with patch('dreamstime.server.platform.system',return_value='Darwin'), patch.object(app,'start_sensor') as start:
                app.watchdog_tick(100)
                start.assert_called_once()
                app.sensor_stopped_intentionally = False
                app.tracker.pause(True)
                app.watchdog_tick(200)
                self.assertEqual(start.call_count,1)
                app.tracker.pause(False)
                app.watchdog_stop.set()
                app.watchdog_tick(300)
                self.assertEqual(start.call_count,1)
            app.tracker.close()
