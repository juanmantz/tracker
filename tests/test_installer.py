import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipIf(sys.platform == 'darwin', 'Linux runtime/launch-tool fixtures; the real bundled app is installed and tested in the mac-installer workflow.')
class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='Dreams install test ')
        self.base = Path(self.temp.name)
        self.source = self.base / 'Downloads' / 'Dreams Time.app'
        self.support = self.base / 'Application Support' / 'Dreams Time'
        self.applications = self.base / 'Applications'
        self.open_log = self.base / 'opened.txt'
        self.alert_log = self.base / 'alerts.txt'
        self.runtime = self.support / 'runtime-3.12.15-arm64'
        self.runtime.mkdir(parents=True)
        (self.runtime / 'python/bin').mkdir(parents=True)
        self.wrapper(self.runtime / 'python/bin/python3', f'exec "{sys.executable}" "$@"')
        resources = self.source / 'Contents/Resources/project'
        resources.mkdir(parents=True)
        for directory in ('dreamstime', 'native', 'web'):
            shutil.copytree(ROOT / directory, resources / directory, ignore=shutil.ignore_patterns('__pycache__'))
        launch = self.source / 'Contents/MacOS/DreamsTime'
        launch.parent.mkdir()
        shutil.copyfile(ROOT / 'scripts/launch-mac.sh', launch); launch.chmod(0o755)
        self.launch = launch
        self.wrapper(self.base / 'open', 'printf "%s\\n" "$*" >> "$MOCK_OPEN_LOG"')
        self.wrapper(self.base / 'osascript', 'printf "%s\\n" "$*" >> "$MOCK_ALERT_LOG"')
        self.wrapper(self.base / 'ditto', f'exec "{sys.executable}" -c \'import shutil,sys;shutil.copytree(sys.argv[1],sys.argv[2])\' "$@"')
        import socket
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0)); self.port = s.getsockname()[1]
        self.env = dict(os.environ, DREAMSTIME_SUPPORT_DIR=str(self.support), DREAMSTIME_APPLICATIONS_DIR=str(self.applications), DREAMSTIME_OPEN=str(self.base/'open'), DREAMSTIME_OSASCRIPT=str(self.base/'osascript'), DREAMSTIME_DITTO=str(self.base/'ditto'), DREAMSTIME_ARCH='arm64', DREAMSTIME_PORT=str(self.port), MOCK_OPEN_LOG=str(self.open_log), MOCK_ALERT_LOG=str(self.alert_log))

    def wrapper(self, path, command):
        path.write_text('#!/bin/bash\nset -e\n'+command+'\n'); path.chmod(0o755)

    def tearDown(self):
        pid_file = self.support / 'tracker.pid'
        if pid_file.exists():
            try: os.kill(int(pid_file.read_text()), signal.SIGTERM)
            except ProcessLookupError: pass
        self.temp.cleanup()

    def run_launcher(self):
        return subprocess.run(['/bin/bash', str(self.launch)], env=self.env, capture_output=True, text=True, timeout=20)

    def test_cold_install_opens_ready_ui_without_system_python_or_compiler(self):
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, (self.support/'launcher.log').read_text())
        self.assertTrue((self.applications/'Dreams Time.app/Contents/MacOS/DreamsTime').exists())
        self.assertIn('/?welcome=1', self.open_log.read_text())
        self.assertFalse(self.alert_log.exists())
        self.assertFalse((self.support/'.launch-lock').exists())

    def test_second_launch_reuses_existing_process(self):
        self.assertEqual(self.run_launcher().returncode, 0)
        pid = (self.support/'tracker.pid').read_text()
        self.assertEqual(self.run_launcher().returncode, 0)
        self.assertEqual((self.support/'tracker.pid').read_text(), pid)
        self.assertEqual(len(self.open_log.read_text().splitlines()), 2)

    def test_extraction_is_checked_and_installed_once(self):
        source = Path('/tmp/dreamstime-arm64.tar.gz')
        if not source.exists(): self.skipTest('Mac runtime archive not downloaded in this environment')
        shutil.rmtree(self.runtime)
        archive = self.source/'Contents/Resources/runtime/arm64.tar.gz'
        archive.parent.mkdir(); shutil.copyfile(source, archive)
        # The real archive hash is checked. A fixture tar creates a Linux-executable
        # runtime to test the remaining install flow without running Mach-O on Linux.
        self.wrapper(self.base/'tar', f'mkdir -p "$4/python/bin"\nprintf \'#!/bin/bash\\nexec "{sys.executable}" "$@"\\n\' > "$4/python/bin/python3"\nchmod +x "$4/python/bin/python3"')
        self.env['DREAMSTIME_TAR'] = str(self.base/'tar')
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, (self.support/'launcher.log').read_text())
        self.assertTrue((self.runtime/'python/bin/python3').is_file())
        self.assertFalse(any(self.support.glob('.runtime.*')))

    def test_corrupt_runtime_fails_with_visible_recovery(self):
        shutil.rmtree(self.runtime)
        archive = self.source/'Contents/Resources/runtime/arm64.tar.gz'
        archive.parent.mkdir(); archive.write_bytes(b'not a python runtime')
        self.assertNotEqual(self.run_launcher().returncode, 0)
        self.assertIn('Setup did not finish', self.alert_log.read_text())
        self.assertFalse((self.support/'tracker.pid').exists())
        self.assertFalse((self.support/'.launch-lock').exists())

    def test_update_replaces_old_running_server_and_preserves_data(self):
        init = self.source/'Contents/Resources/project/dreamstime/__init__.py'
        init.write_text(init.read_text().replace('0.12.0', '0.2.0'))
        self.assertEqual(self.run_launcher().returncode, 0)
        first_pid = (self.support/'tracker.pid').read_text()
        token = (self.support/'pairing-token').read_text()
        init.write_text(init.read_text().replace('0.2.0', '0.12.0'))
        self.assertEqual(self.run_launcher().returncode, 0, (self.support/'launcher.log').read_text())
        self.assertNotEqual((self.support/'tracker.pid').read_text(), first_pid)
        self.assertEqual((self.support/'pairing-token').read_text(), token)
        from http.client import HTTPConnection
        c=HTTPConnection('127.0.0.1',self.port,timeout=3)
        c.request('GET','/health')
        import json
        self.assertEqual(json.loads(c.getresponse().read())['version'],'0.12.0')
        c.close()

    def test_same_version_legacy_backend_is_replaced_for_app_owned_capture(self):
        self.assertEqual(self.run_launcher().returncode, 0)
        previous_pid = (self.support/'tracker.pid').read_text()
        token = (self.support/'pairing-token').read_text()
        self.env['DREAMSTIME_NATIVE_HOST'] = '1'
        self.assertEqual(self.run_launcher().returncode, 0, (self.support/'launcher.log').read_text())
        self.assertNotEqual((self.support/'tracker.pid').read_text(), previous_pid)
        self.assertEqual((self.support/'pairing-token').read_text(), token)
        from http.client import HTTPConnection
        import json
        connection = HTTPConnection('127.0.0.1', self.port, timeout=3)
        connection.request('GET', '/health')
        self.assertEqual(json.loads(connection.getresponse().read())['capture_host'], 'app')
        connection.close()

    def test_stale_launch_lock_is_recovered(self):
        lock = self.support/'.launch-lock'; lock.mkdir(); (lock/'pid').write_text('99999999')
        self.assertEqual(self.run_launcher().returncode, 0)
        self.assertFalse(lock.exists())

if __name__ == '__main__': unittest.main()
