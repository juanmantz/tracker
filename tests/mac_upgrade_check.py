"""Installer smoke checks on an isolated macOS CI user, never a real account."""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SUPPORT = Path.home() / 'Library/Application Support/Dreams Time'
EVIDENCE = ROOT / 'artifacts/native-release'


def fingerprint(text):
    return hashlib.sha256(text.encode()).hexdigest()


def prepare():
    from dreamstime.server import App
    from dreamstime.replay import BASE
    app = App(SUPPORT)
    for offset in range(0, 122, 2):
        app.tracker.ingest({'ts': BASE + offset, 'app': 'fixture.editor',
                            'title': 'Installer preservation fixture', 'idle': 0})
    assert app.tracker.report('2026-10-05')['total_seconds'] == 120
    previous = {'pairing': fingerprint(app.token), 'installation': fingerprint(app.installation)}
    app.tracker.close()
    (EVIDENCE / 'upgrade-before.json').write_text(json.dumps(previous))
    # Run the real prior service contract; mark the copied source as the older
    # build so the new launcher must stop and replace an already running service.
    copy = Path(tempfile.mkdtemp(prefix='dreamstime-prior-'))
    shutil.copytree(ROOT / 'dreamstime', copy / 'dreamstime')
    (copy / 'dreamstime/__init__.py').write_text('__version__ = "0.6.0"\n')
    with (EVIDENCE / 'prior-service.log').open('w') as log:
        subprocess.Popen([sys.executable, '-m', 'dreamstime.server', '--no-browser', '--no-sensor',
                          '--data-dir', str(SUPPORT)], cwd=copy, stdout=log, stderr=log,
                         start_new_session=True)
    for _ in range(40):
        try:
            with urlopen('http://127.0.0.1:43123/health', timeout=1) as response:
                assert json.load(response)['version'] == '0.6.0'
            return
        except OSError:
            time.sleep(.1)
    raise AssertionError('Prior service did not start')


def verify():
    from dreamstime.core import Tracker
    before = json.loads((EVIDENCE / 'upgrade-before.json').read_text())
    tracker = Tracker(SUPPORT / 'activity.sqlite')
    assert tracker.report('2026-10-05')['total_seconds'] == 120
    assert fingerprint(tracker.setting('installation')) == before['installation']
    tracker.close()
    token = (SUPPORT / 'pairing-token').read_text().strip()
    assert fingerprint(token) == before['pairing']
    (EVIDENCE / 'upgrade-check.json').write_text(json.dumps({
        'prior_history_seconds': 120, 'preserved_history_seconds': 120,
        'pairing_preserved': True, 'installation_preserved': True}))

    # Drive the installed application's exact failing button through the live
    # public provider. Only registers a public PKCE client; no account sign-in,
    # token, map reads or Worked measurements are performed.
    request = Request('http://127.0.0.1:43123/api/dreams/connect', data=b'{"native":true}',
                      headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
    with urlopen(request, timeout=50) as response:
        result = json.load(response)
    destination = urlsplit(result['url'])
    query = parse_qs(destination.query)
    assert destination.scheme == 'https' and destination.netloc == 'dreams.checklists.workers.dev'
    assert destination.path == '/oauth/authorize'
    assert query['redirect_uri'] == ['http://127.0.0.1:43123/oauth/callback']
    assert query['code_challenge_method'] == ['S256']
    assert set(query['scope'][0].split()) == {'mcp:read', 'mcp:write', 'offline_access'}
    assert query['resource'] == ['https://dreams.checklists.workers.dev/mcp']
    (EVIDENCE / 'live-setup-check.json').write_text(json.dumps({
        'discovery_and_registration_ok': True, 'pkce_and_scopes_ok': True,
        'client_id': query['client_id'][0], 'account_data_accessed': False,
        'measurements_written': 0}))


if __name__ == '__main__':
    {'prepare': prepare, 'verify': verify}[sys.argv[1]]()
