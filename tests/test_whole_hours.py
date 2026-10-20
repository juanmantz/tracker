"""Accelerated measured-time checks; never write to the owner's account."""
import copy
import unittest
from dreamstime.dreams import build_worked_batch
from tests.dreams_provider import map_fixture


def report(seconds, other=0):
    return {'reviewed': True, 'week': '2026-10-05', 'totals': {'atlas': seconds, 'birch': other},
            'projects': [{'id': 'atlas', 'dreams_id': 'atlas', 'name': 'Atlas Studio'},
                         {'id': 'birch', 'dreams_id': 'birch', 'name': 'Birch Client'}]}


class WholeHoursTests(unittest.TestCase):
    def test_subhour_work_has_no_publishable_command(self):
        batch = build_worked_batch(report(3599.999999), map_fixture(), 'mac')
        self.assertEqual(batch['commands'], [])

    def test_complete_hours_floor_per_project_and_keep_week_identity(self):
        batch = build_worked_batch(report(7199, 3599), map_fixture(), 'mac')
        self.assertEqual(len(batch['commands']), 1)
        measurement = batch['commands'][0]['measurement']
        self.assertEqual(measurement['amount'], {'value': 1, 'unit': 'hours'})
        self.assertEqual(measurement['period'], {'kind': 'Week', 'start': '2026-10-05', 'end': '2026-10-11'})
        self.assertEqual(measurement['scope'], 'Own')

    def test_two_local_assignments_for_same_destination_combine_before_floor(self):
        data = report(1900, 1900)
        data['projects'][1]['dreams_id'] = 'atlas'
        batch = build_worked_batch(data, map_fixture(), 'mac')
        self.assertEqual([c['measurement']['amount']['value'] for c in batch['commands']], [1])

    def test_correction_below_an_hour_clears_only_this_devices_stable_snapshot(self):
        state = map_fixture()
        prior = build_worked_batch(report(3600), state, 'mac')['commands'][0]['measurement']
        state['nodes'][0]['measurements'] = [copy.deepcopy(prior)]
        corrected = build_worked_batch(report(30), state, 'mac')['commands'][0]['measurement']
        self.assertEqual(corrected['id'], prior['id'])
        self.assertEqual(corrected['amount']['value'], 0)
        self.assertEqual(prior['amount']['value'], 1)


from tests.test_recognition_sync import IntegrationTests
from dreamstime.connection import DreamsConnection
from dreamstime.sync import DreamsSync
from dreamstime.replay import BASE


class VerifiedPublicationTests(unittest.TestCase):
    setUp = IntegrationTests.setUp
    tearDown = IntegrationTests.tearDown
    connect = IntegrationTests.connect
    api = IntegrationTests.api
    activity = IntegrationTests.activity
    hours = IntegrationTests.hours

    def test_partial_time_is_retained_then_exactly_one_hour_is_verified_without_waiting(self):
        self.connect(); self.activity(3598)
        waiting = self.app.sync.send('2026-10-05')
        self.assertTrue(waiting['skipped'])
        self.assertEqual(waiting['published_hours'], 0)
        self.assertEqual(self.hours(), [])
        self.assertEqual(self.provider.writes, [])
        self.assertIsNone(self.app.tracker.setting('last_sync'))
        self.activity(3600)
        # Replayed old samples are rejected; the newly measured boundary is kept.
        self.assertEqual(self.app.tracker.report('2026-10-05')['totals']['atlas'], 3600)
        saved = self.app.sync.send('2026-10-05')
        self.assertEqual(saved['published_hours'], 1)
        self.assertEqual(saved['verification'], 'dreamstime/published/v1')
        self.assertEqual(self.hours(), [1])

    def test_partial_minutes_and_unknown_time_do_not_rewrite_unchanged_whole_hours(self):
        self.connect(); self.activity(3600)
        self.app.sync.send('2026-10-05')
        count = len(self.provider.writes)
        self.activity(3660)
        self.app.tracker.ingest({'ts': BASE+3662, 'app':'other.editor','title':'Unknown document','idle':0})
        self.app.tracker.ingest({'ts': BASE+3664, 'app':'other.editor','title':'Unknown document','idle':0})
        result = self.app.sync.send('2026-10-05')
        self.assertTrue(result['unchanged'])
        self.assertEqual(len(self.provider.writes), count)
        self.assertEqual(result['published_hours'], 1)
        self.assertEqual(result['retained_seconds'], 62)
        self.assertEqual(result['unassigned_seconds'], 2)

    def test_successful_response_that_drops_hours_cannot_be_called_saved(self):
        self.connect(); self.activity()
        self.provider.discard_measurements = True
        with self.assertRaisesRegex(ValueError, 'did not confirm'):
            self.app.sync.send('2026-10-05')
        self.assertIsNone(self.app.tracker.setting('last_sync'))
        self.assertIsNone(self.app.tracker.setting('pending_sync'))
        self.assertEqual(self.hours(), [])
        self.provider.discard_measurements = False
        self.assertEqual(self.app.sync.send('2026-10-05')['published_hours'], 1)

    def test_failed_readback_keeps_identical_request_for_retry_after_restart(self):
        self.connect(); self.activity()
        self.provider.fail_read_after_write = True
        with self.assertRaises(ValueError):
            self.app.sync.send('2026-10-05')
        pending = copy.deepcopy(self.app.tracker.setting('pending_sync'))
        self.assertIsNotNone(pending)
        self.assertIsNone(self.app.tracker.setting('last_sync'))
        self.app.connection = DreamsConnection(self.directory.name, self.app.port, self.provider.origin)
        self.app.sync = DreamsSync(self.app.tracker, self.app.connection, self.app.installation)
        self.assertEqual(self.app.sync.send('2026-10-05')['published_hours'], 1)
        self.assertEqual(len(self.provider.writes), 1)
        self.assertEqual(pending['batch'], self.provider.writes[0])

    def test_legacy_fractional_pending_request_is_retried_without_changing_its_body(self):
        self.connect(); self.activity(60)
        pending = {'week':'2026-10-05','signature':'old','seconds':60,'unassigned_seconds':0,
            'batch': {'baseRevision':self.provider.map['revision'], 'requestId':'old-request', 'commands':[]}}
        command = build_worked_batch(report(3600), self.provider.map, self.app.installation)['commands'][0]
        command['measurement']['amount']['value'] = round(60/3600, 6)
        pending['batch']['commands'] = [command]
        # Model a pre-upgrade accepted request, normalized to zero by Dreams.
        self.provider.requests['old-request'] = {'revision':self.provider.map['revision']}
        self.app.tracker.set_setting('pending_sync', pending)
        saved = self.app.sync.send('2026-10-05')
        self.assertEqual(saved['published_hours'], 0)
        self.assertEqual(saved['retained_seconds'], 60)
        self.assertEqual(self.provider.writes, [])
