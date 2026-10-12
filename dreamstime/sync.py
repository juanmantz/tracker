"""Sync frozen totals, retaining the exact request after an uncertain write."""
import threading
import time
from datetime import datetime, timedelta

from .connection import Conflict, Rejected
from .core import digest, monday, week_bounds
from .dreams import build_worked_batch


class DreamsSync:
    def __init__(self, tracker, connection, installation):
        self.tracker = tracker
        self.connection = connection
        self.installation = installation
        self.lock = threading.RLock()
        self.stop = threading.Event()

    def status(self):
        return {**self.connection.status(), 'weekly': self.tracker.setting('weekly_sync', False),
                'last': self.tracker.setting('last_sync'), 'error': self.tracker.setting('sync_error'),
                'pending': bool(self.tracker.setting('pending_sync')), 'weeks': list(self.tracker.setting('synced_weeks', {}))}

    def refresh(self):
        state = self.connection.call('get_map')
        if not isinstance(state, dict) or not isinstance(state.get('revision'), int):
            raise ValueError('Dreams returned an invalid project map.')
        count = self.tracker.import_projects(state)
        # Store only work metadata, identities and this device's measurement IDs.
        # The full finance map is used in memory for validation only.
        self.tracker.set_setting('dreams_project_count', count)
        return state

    def send(self, week):
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
                # The explicit Sync button / enabled weekly schedule authorizes assigned totals.
                # Unassigned time is omitted and remains visible for a later correction.
                report['reviewed'] = True
                signature = digest([report['totals'], [(p['id'], p.get('dreams_id')) for p in report['projects']]])
                last = self.tracker.setting('synced_weeks', {}).get(week)
                batch = build_worked_batch(report, state, self.installation)
                nodes = {node['id']: node for node in state['nodes']}
                def matches_remote(command):
                    expected = command['measurement']
                    saved = next((m for m in nodes[command['id']].get('measurements', []) if m.get('id') == expected['id']), {})
                    return all(saved.get(key) == expected.get(key) for key in ('metric','amount','basis','period','scope','source'))
                if last and last['signature'] == signature and all(matches_remote(c) for c in batch['commands']):
                    self.tracker.set_setting('sync_error', None)
                    return {**last, 'unchanged': True}
                pending = {'week': week, 'signature': signature, 'batch': batch,
                           'seconds': sum(v for k,v in report['totals'].items() if k != 'unassigned'),
                           'unassigned_seconds': report['totals'].get('unassigned', 0)}
                self.tracker.set_setting('pending_sync', pending)
                try:
                    result = self.connection.call('apply_changes', batch)
                except Conflict:
                    self.tracker.set_setting('pending_sync', None)
                    # New map on the next action; do not spin on concurrent Dreams edits.
                    raise ValueError('Dreams changed during sync. Your hours are saved. Click Sync again.') from None
                except Rejected:
                    self.tracker.set_setting('pending_sync', None)
                    raise
                self.complete(pending, result)
                return self.status()['last']
            except ValueError as error:
                self.tracker.set_setting('sync_error', str(error))
                raise

    def complete(self, pending, result):
        last = {k:pending[k] for k in ('week','signature','seconds','unassigned_seconds')}
        last.update(at=time.time(), revision=result.get('revision') if isinstance(result, dict) else None)
        weeks = self.tracker.setting('synced_weeks', {})
        weeks[pending['week']] = last
        with self.tracker.lock, self.tracker.db:
            self.tracker.set_setting('synced_weeks', weeks)
            self.tracker.set_setting('last_sync', last)
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

    def start(self):
        def run():
            while not self.stop.is_set():
                try:
                    self.weekly_tick()
                except (ValueError, OSError):
                    pass  # status exposes failure, and exact pending request is retained
                self.stop.wait(300)
        threading.Thread(target=run, daemon=True).start()
