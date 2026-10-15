"""Explain actual capture state separately from a passing synthetic self-test."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def recording_status(tracker, now, *, enabled, running, error=None, samples=0):
    snap = tracker.snapshot(now)
    current = snap['current']
    last = snap['health']['last_sample']
    age = None if last is None else max(0, now-last)
    with tracker.lock:
        zone = ZoneInfo(tracker.timezone)
        day = datetime.fromtimestamp(now, zone).date()
        start = datetime.combine(day, datetime.min.time(), zone).timestamp()
        end = datetime.combine(day+timedelta(days=1), datetime.min.time(), zone).timestamp()
        today = round(sum(s['seconds'] for s in tracker.segments(start, end)), 3)
    if tracker.paused:
        state, detail = 'paused', 'Tracking is paused. Resume to collect activity.'
    elif error:
        state, detail = 'failed', error
    elif not enabled:
        state, detail = 'off', 'Capture has not started. Choose Start tracking.'
    elif age is None:
        state, detail = 'starting' if running else 'failed', 'Waiting for the first real Mac sample.' if running else 'The capture process is not running. Restart capture.'
    elif age > tracker.max_gap:
        state, detail = 'stale', 'No recent activity samples. Restart capture.'
    elif not running:
        state, detail = 'failed', 'The capture process stopped. Restart capture.'
    elif current and current['active']:
        state, detail = 'recording', ('A connected call is being timed, including listening time.' if current['context'].get('activity_kind') == 'call' else 'Actual foreground activity is being saved.')
    elif current and current['idle'] >= tracker.idle_after:
        state, detail = 'idle', 'You are idle. The idle tail is excluded from recorded time.'
    elif current and current['context']['source'] == 'browser context missing':
        state, detail = 'browser_unavailable', 'This browser needs the companion extension. Switch to the ChatGPT or Figma desktop app to test native capture.'
    elif current and current['context'].get('excluded'):
        state, detail = 'excluded', 'This activity is excluded from recording.'
    else:
        state, detail = 'locked', 'The Mac session is locked or inactive. No time is being added.'
    return {'state':state, 'detail':detail, 'today_seconds':today, 'sample_count':samples, 'last_sample_age_seconds':None if age is None else round(age, 1), 'process_running':running}
