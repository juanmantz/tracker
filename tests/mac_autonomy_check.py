"""Exercise crash recovery on the actual installed Mac app, in isolated CI."""
import json
import os
import signal
import subprocess
import time
from pathlib import Path
from urllib.request import Request, urlopen

SUPPORT = Path.home() / 'Library/Application Support/Dreams Time'
APP = '/Applications/Dreams Time.app/Contents/MacOS/DreamsTime'
PROOF = Path('artifacts/native-release/autonomy-check.json')
token = (SUPPORT / 'pairing-token').read_text().strip()


def api(path, body=None):
    request = Request('http://127.0.0.1:43123' + path,
                      data=None if body is None else json.dumps(body).encode(),
                      headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with urlopen(request, timeout=2) as response:
        return json.load(response)


def wait_for(check, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if check(): return
        except (OSError, ValueError):
            pass
        time.sleep(.5)
    raise AssertionError('Installed app did not recover in the allowed time')


def service_pid():
    return int((SUPPORT / 'tracker.pid').read_text())


before = api('/api/diagnostics')['recording']['sample_count']
backend = service_pid()
sensor = api('/api/diagnostics')['health']['collector']['collector_pid']
assert api('/api/diagnostics')['health']['collector']['collector_bundle'] == 'local.dreamstime.companion'
os.kill(sensor, signal.SIGKILL)
wait_for(lambda: api('/api/diagnostics')['health'].get('collector', {}).get('collector_pid') != sensor
         and api('/api/diagnostics')['recording']['sample_count'] > before + 2, 100)
subprocess.run(['/bin/launchctl', 'print', 'gui/' + str(os.getuid()) + '/local.dreamstime.start'], check=True, stdout=subprocess.DEVNULL)
os.kill(backend, signal.SIGKILL)
wait_for(lambda: service_pid() != backend and api('/health')['version'] == '0.8.2', 100)
wait_for(lambda: api('/api/diagnostics')['recording']['sample_count'] >= 2, 20)
api('/api/quit', {})
time.sleep(2)
assert (SUPPORT / '.stopped').exists()
subprocess.run([APP, '--background'], check=True, timeout=15)
try:
    api('/health')
except OSError:
    pass
else:
    raise AssertionError('Explicit Quit must suppress automatic relaunch')
subprocess.run([APP, '--smoke-test'], check=True, timeout=65)
subprocess.run(['/usr/bin/open', '-g', '/Applications/Dreams Time.app'], check=True)
wait_for(lambda: api('/api/diagnostics')['recording']['sample_count'] >= 2, 20)
assert not (SUPPORT / '.stopped').exists()
assert api('/api/snapshot')['dreams']['automatic'] is True
PROOF.write_text(json.dumps({'sensor_crash_recovered': True, 'service_crash_recovered_by_app': True,
                            'quit_respected': True, 'reopen_resumed': True, 'automatic_saving_default': True}))
print('Installed app recovered from collector and service crashes; Quit and reopen worked.')
