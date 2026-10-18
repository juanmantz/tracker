"""Sync frozen totals, retaining the exact request after an uncertain write."""
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import __version__
from .connection import Conflict, Rejected
from .core import digest, monday, week_bounds
from .dreams import build_worked_batch
from decimal import Decimal, ROUND_FLOOR
from .recognition import WORK_KINDS
from .coordination import Coordination


class DreamsSync:
    def __init__(self, tracker, connection, installation):
        self.tracker = tracker
        self.connection = connection
        self.installation = installation
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.coordination = Coordination(tracker, connection, installation)
        self.thread = None

    def status(self):
        return {**self.connection.status(), 'weekly': self.tracker.setting('automatic_sync', True),
                'automatic': self.tracker.setting('automatic_sync', True),
                'checked_at': self.tracker.setting('auto_checked_at'),
                'reviewed_at': self.tracker.setting('cloud_reviewed_at'),
                'heartbeat_at': self.tracker.setting('last_heartbeat'),
                'retrying': bool(self.tracker.setting('auto_error_since')),
                'action_required': 'sign-in' if 'sign-in expired' in (self.tracker.setting('sync_error') or '') else None,
                'last': self.tracker.setting('last_sync'), 'error': self.tracker.setting('sync_error'),
                'publication': self.tracker.setting('publication'),
                'context_access': ('denied' if self.tracker.health.get('collector', {}).get('ax_trusted') is False and not self.tracker.health.get('accessibility') else 'allowed' if self.tracker.health.get('accessibility') else 'unknown'),
                'pending': bool(self.tracker.setting('pending_sync')), 'weeks': list(self.tracker.setting('synced_weeks', {}))}

    def refresh(self):
        state = self.connection.call('get_map')
        if not isinstance(state, dict) or not isinstance(state.get('revision'), int):
            raise ValueError('Dreams returned an invalid project map.')
        count = self.tracker.import_projects(state)
        # Store only work metadata, identities and this device's measurement IDs.
        # The full finance map is used in memory for validation only.
        self.tracker.set_setting('dreams_project_count', count)
        self.coordination.consume(state)
        return state

    def send(self, week, *, automatic=False):
        with self.lock:
            week_bounds(week, self.tracker.timezone)
            try:
                pending = self.tracker.setting('pending_sync')
                if pending:
                    # Always settle the saved write first, even if a different week was selected.
                    try:
                        result = self.connection.call('apply_changes', pending['batch'])
                    except Conflict:
                        # An explicit conflict proves the pending batch wasn't applied.
                        self.tracker.set_setting('pending_sync', None)
                    except Rejected:
                        self.tracker.set_setting('pending_sync', None)
                        raise
                    else:
                        self.complete(pending, result)
                        if pending['week'] == week:
                            return self.status()['last']
                state = self.refresh()
                report = self.tracker.report(week)
                if automatic:
                    # Archived/deleted assets and unlinked local projects must not
                    # prevent current work saving. Preserve archived snapshots;
                    # they describe historical work on a now-archived destination.
                    active = {n['id'] for n in state['nodes'] if not n.get('archived')}
                    state = {**state, 'nodes': [n for n in state['nodes'] if n['id'] in active]}
                    projects = [p for p in report['projects'] if p.get('dreams_id') in active]
                    included = {p['id'] for p in projects}
                    report = {**report, 'projects': projects, 'totals': {
                        **{k:v for k,v in report['totals'].items() if k in included},
                        'unassigned': sum(v for k,v in report['totals'].items() if k not in included)}}
                # The explicit Sync button / enabled weekly schedule authorizes assigned totals.
                # Unassigned time is omitted and remains visible for a later correction.
                report['reviewed'] = True
                signature = digest([report['totals'], [(p['id'], p.get('dreams_id')) for p in report['projects']]])
                batch = build_worked_batch(report, state, self.installation)
                assigned = sum(v for k,v in report['totals'].items() if k != 'unassigned')
                pending = {'week': week, 'signature': signature, 'batch': batch,
                           'seconds': assigned, 'unassigned_seconds': report['totals'].get('unassigned', 0)}
                if not batch['commands']:
                    waiting = {k:pending[k] for k in ('week','seconds','unassigned_seconds')}
                    waiting.update(state='waiting_for_hour' if assigned else 'unassigned',
                                   published_hours=0, retained_seconds=assigned, at=time.time(), skipped=True)
                    self.tracker.set_setting('publication', waiting)
                    self.tracker.set_setting('sync_error', None)
                    return waiting
                # Compare the actual remote snapshots, independent of unassigned
                # activity or additional minutes retained on the Mac.
                if self.matches_publication(pending, state):
                    self.complete(pending, {'revision': state['revision']}, state=state)
                    return {**self.status()['last'], 'unchanged': True}
                self.tracker.set_setting('pending_sync', pending)
                try:
                    result = self.connection.call('apply_changes', batch)
                except Conflict:
                    self.tracker.set_setting('pending_sync', None)
                    # New map on the next action; do not spin on concurrent Dreams edits.
                    raise ValueError('Dreams changed during saving. Your hours are safe; automatic saving will retry.') from None
                except Rejected:
                    self.tracker.set_setting('pending_sync', None)
                    raise
                self.complete(pending, result)
                return self.status()['last']
            except ValueError as error:
                self.tracker.set_setting('sync_error', str(error))
                raise

    @staticmethod
    def published_hours(measurement):
        # Also safely settle a saved pre-upgrade fractional request. The exact
        # original request remains untouched for idempotent retry.
        return int((Decimal(str(measurement['amount']['value']))).to_integral_value(rounding=ROUND_FLOOR))

    def matches_publication(self, pending, state):
        nodes = {n['id']: n for n in state.get('nodes', [])}
        for command in pending['batch']['commands']:
            expected = command['measurement']
            hours = self.published_hours(expected)
            node = nodes.get(command['id'])
            if not node or node.get('archived') or node.get('kind') not in WORK_KINDS:
                return False
            saved = next((m for m in node.get('measurements', []) if m.get('id') == expected['id']), None)
            # The Dreams whole-hour gate may remove a zero correction entirely.
            if hours == 0 and saved is None:
                continue
            if not saved or isinstance(saved.get('amount', {}).get('value'), bool) or saved.get('amount') != {'value': hours, 'unit': 'hours'}:
                return False
            if any(saved.get(k) != expected.get(k) for k in ('metric','basis','scope','source')):
                return False
            if saved.get('period', {}).get('kind') not in ('Week', 'Custom'):
                return False
            if any(saved.get('period', {}).get(k) != expected.get('period', {}).get(k) for k in ('start','end')):
                return False
        return True

    def complete(self, pending, result, *, state=None):
        # HTTP success is only an accepted request. A fresh map is the receipt.
        # Read failures leave pending_sync intact for the exact retry after restart.
        state = self.connection.call('get_map') if state is None else state
        if not self.matches_publication(pending, state):
            # A confirmed response plus a successful read proves a mismatch,
            # rather than an uncertain transport outcome. Rebuild on the next tick.
            self.tracker.set_setting('pending_sync', None)
            raise ValueError('Dreams did not confirm the published project hours. Recorded time is safe; automatic saving will retry.')
        last = {k:pending[k] for k in ('week','signature','seconds','unassigned_seconds')}
        hours = sum(self.published_hours(c['measurement']) for c in pending['batch']['commands'])
        last.update(at=time.time(), revision=state.get('revision'), published_hours=hours,
                    retained_seconds=max(0, pending['seconds']-hours*3600),
                    verification='dreamstime/published/v1', state='verified')
        weeks = self.tracker.setting('synced_weeks', {})
        weeks[pending['week']] = last
        with self.tracker.lock, self.tracker.db:
            self.tracker.set_setting('synced_weeks', weeks)
            self.tracker.set_setting('last_sync', last)
            self.tracker.set_setting('publication', last)
            self.tracker.set_setting('pending_sync', None)
            self.tracker.set_setting('sync_error', None)

    def weekly_tick(self, now=None):
        if not self.tracker.setting('weekly_sync', False) or not self.connection.status()['connected']:
            return
        current = monday(now or time.time(), self.tracker.timezone)
        with self.tracker.lock:
            weeks = {monday(r[0], self.tracker.timezone) for r in self.tracker.db.execute('SELECT start FROM segments')}
        # Corrections to old weeks are included; partial current week waits until Monday.
        for week in sorted(w for w in weeks if w < current):
            report = self.tracker.report(week)
            if any(v for k,v in report['totals'].items() if k != 'unassigned') or week in self.tracker.setting('synced_weeks', {}):
                self.send(week)

    def automatic_tick(self, now=None):
        now = time.time() if now is None else now
        if not self.tracker.setting('automatic_sync', True) or not self.connection.status()['connected']:
            return
        with self.lock:
            try:
                self.coordination.settle()
                self.refresh()
                self.tracker.set_setting('auto_checked_at', now)
                day = datetime.fromtimestamp(now, ZoneInfo(self.tracker.timezone)).date().isoformat()
                if self.tracker.setting('local_review_day') != day:
                    with self.tracker.lock, self.tracker.db:
                        self.tracker.reclassify()
                    self.tracker.set_setting('local_review_day', day)
                    self.tracker.set_setting('local_review_at', now)
                    self.tracker.set_setting('auto_dirty', True)
                pending = self.tracker.setting('pending_sync')
                if pending:
                    self.send(pending['week'], automatic=True)
                if now - self.tracker.setting('auto_saved_at', 0) >= 300 or self.tracker.setting('auto_dirty', False):
                    with self.tracker.lock:
                        weeks = {monday(r[0], self.tracker.timezone) for r in self.tracker.db.execute('SELECT start FROM segments')}
                    weeks.update(self.tracker.setting('synced_weeks', {}))
                    for week in sorted(weeks):
                        if self.stop.is_set():
                            return
                        report = self.tracker.report(week)
                        if any(v for k,v in report['totals'].items() if k != 'unassigned') or week in self.tracker.setting('synced_weeks', {}):
                            self.send(week, automatic=True)
                    self.tracker.set_setting('auto_saved_at', now)
                    self.tracker.set_setting('auto_dirty', False)
                self.tracker.set_setting('sync_error', None)
                self.tracker.set_setting('auto_error_since', None)
                collector = self.tracker.health.get('collector', {})
                profile = digest([__version__, collector.get('collector_bundle'),
                                  collector.get('collector_pid'), collector.get('ax_trusted'),
                                  bool(self.tracker.health.get('accessibility'))])
                if (now - self.tracker.setting('last_heartbeat', 0) >= 900
                        or profile != self.tracker.setting('published_collector_profile')):
                    if self.coordination.publish(self.refresh(), now) is not False:
                        self.tracker.set_setting('published_collector_profile', profile)
            except (ValueError, OSError) as error:
                self.tracker.set_setting('sync_error', str(error))
                if not self.tracker.setting('auto_error_since'):
                    self.tracker.set_setting('auto_error_since', now)
                raise

    def start(self):
        def run():
            while not self.stop.is_set():
                try:
                    self.automatic_tick()
                except (ValueError, OSError):
                    pass  # status exposes failure, and exact pending request is retained
                self.stop.wait(60)
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
