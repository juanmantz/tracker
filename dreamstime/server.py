from __future__ import annotations

import argparse
import hmac
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .account import import_chatgpt
from .core import Tracker, monday, digest
from .dreams import build_worked_batch
from .connection import DreamsConnection
from .sync import DreamsSync
from .replay import workday
from .quickcheck import QuickCheck
from .status import recording_status
from . import __version__

ROOT = Path(__file__).resolve().parent.parent


class App:
    def __init__(self, directory, port=43123):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
        self.directory = directory
        self.tracker = Tracker(directory / "activity.sqlite")
        bootstrap_path = directory / 'bootstrap-projects.json'
        if bootstrap_path.exists():
            try:
                bootstrap = json.loads(bootstrap_path.read_text())
                stamp = digest(bootstrap)
                if self.tracker.setting('bootstrap_stamp') != stamp:
                    self.tracker.import_projects(bootstrap)
                    self.tracker.set_setting('bootstrap_stamp', stamp)
                preferences = bootstrap.get('preferences', {})
                if isinstance(preferences, dict) and preferences.get('desktop_context_enabled') is True and self.tracker.setting('desktop_context_enabled') is None:
                    self.tracker.set_setting('desktop_context_enabled', True)
            except (ValueError, TypeError, KeyError, OSError, AttributeError):
                pass  # A broken seed must never prevent tracking or overwrite history.
        token_path = directory / "pairing-token"
        if not token_path.exists():
            token_path.write_text(secrets.token_urlsafe(32))
        os.chmod(token_path, 0o600)
        self.token = token_path.read_text().strip()
        self.installation = self.tracker.setting("installation") or secrets.token_hex(12)
        self.tracker.set_setting("installation", self.installation)
        self.port = port
        self.native_host = os.environ.get("DREAMSTIME_NATIVE_HOST") == "1"
        self.native_last_sample = None
        self.sensor = None
        self.sensor_error = None
        self.demo = None
        self.map = self.tracker.setting("dreams_map")
        self.quickcheck = QuickCheck()
        self.selftest = None
        self.sample_count = 0
        self.sensor_detail = None
        self.sensor_started_at = None
        self.sensor_stopped_intentionally = False
        self.connection = DreamsConnection(directory, port)
        self.sync = DreamsSync(self.tracker, self.connection, self.installation)
        self.oauth_native = False
        self.watchdog_stop = threading.Event()
        self.watchdog_thread = None
        self.last_recovery = 0

    def watchdog_tick(self, now=None):
        now = time.time() if now is None else now
        if self.native_host:
            return  # The app owns collection and restarts a failed service.
        if (platform.system() != 'Darwin' or self.tracker.paused or self.sensor_stopped_intentionally
                or not self.tracker.setting('capture_enabled', False) or self.watchdog_stop.is_set()):
            return
        last = self.tracker.health.get('last_sample') or self.sensor_started_at or 0
        alive = self.sensor and self.sensor.poll() is None
        if (not alive or now - max(last, self.sensor_started_at or 0) > 20) and now - self.last_recovery >= 60:
            self.last_recovery = now
            self.stop_sensor()
            self.tracker.previous = None
            self.start_sensor()
            self.tracker.set_setting('sensor_recoveries', self.tracker.setting('sensor_recoveries', 0) + 1)

    def start_watchdog(self):
        def run():
            while not self.watchdog_stop.wait(10):
                self.watchdog_tick()
        self.watchdog_thread = threading.Thread(target=run, daemon=True)
        self.watchdog_thread.start()

    def start_sensor(self):
        if self.tracker.paused:
            return
        if self.native_host:
            self.sensor_error = None
            self.sensor_started_at = time.time()
            self.sensor_stopped_intentionally = False
            self.tracker.set_setting("capture_enabled", True)
            return
        if platform.system() != "Darwin":
            self.sensor_error = "Native capture requires macOS. Test lab works on this computer."
            return
        if self.sensor and self.sensor.poll() is None:
            return
        binary = ROOT / "native" / "activity-sensor"
        script = ROOT / "native" / "ActivitySensor.js"
        # Installer builds ship a compiled universal collector. The scripting path
        # remains available for developer/source runs without a built collector.
        if binary.exists():
            command = [str(binary)]
        elif script.exists():
            command = ["/usr/bin/osascript", "-l", "JavaScript", str(script)]
        else:
            self.sensor_error = "The app is incomplete. Download Dreams Time again."
            return
        self.sensor_error = None
        self.sensor_detail = None
        self.sensor_started_at = time.time()
        self.sensor_stopped_intentionally = False
        self.tracker.set_setting("capture_enabled", True)
        flags = ["--chatgpt-context"] if self.tracker.setting("desktop_context_enabled", False) else []
        try:
            self.sensor = subprocess.Popen([*command, "--request-permission", *flags], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        except OSError:
            self.sensor_error = "Mac capture could not start. Reopen Dreams Time to retry."
            return

        process = self.sensor

        def read_errors():
            # Keep stderr drained so a native error cannot block the sensor pipe.
            # Our sensor never logs titles, URLs or message content to stderr.
            for line in process.stderr:
                if self.sensor is process:
                    self.sensor_detail = line.strip()[-1000:]

        error_reader = threading.Thread(target=read_errors, daemon=True)
        error_reader.start()

        def read():
            try:
                for line in process.stdout:
                    try:
                        sample = json.loads(line)
                        if self.tracker.ingest(sample):
                            self.sample_count += 1
                            self.quickcheck.observe(sample)
                    except (ValueError, TypeError, KeyError):
                        self.sensor_error = "The sensor sent an invalid sample. Restart the tracker."
                process.wait()
                error_reader.join(timeout=1)
                if self.sensor is process:
                    detail = self.sensor_detail or "No native error details were returned."
                    self.sensor_error = "Mac capture stopped: " + detail
            except Exception:
                if self.sensor is process:
                    self.sensor_error = "The activity sensor disconnected. Restart capture."
        threading.Thread(target=read, daemon=True).start()

    def stop_sensor(self):
        self.sensor_stopped_intentionally = True
        process, self.sensor = self.sensor, None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)

    def accept_native_sample(self, sample):
        if not self.native_host:
            raise ValueError("This service does not use the app-hosted collector.")
        settings = {"ok": True, "paused": self.tracker.paused,
                    "desktop_context_enabled": bool(self.tracker.setting("desktop_context_enabled", False))}
        if self.tracker.paused or sample.get("heartbeat") is True:
            return settings
        if sample.get("collector_bundle") != "local.dreamstime.companion":
            raise ValueError("Expected the Dreams Time app collector.")
        ts = sample.get("ts")
        if not isinstance(ts, (int, float)) or isinstance(ts, bool) or not time.time() - 10 <= ts <= time.time() + 5:
            raise ValueError("Expected a current native sample.")
        if self.tracker.ingest(sample):
            self.native_last_sample = time.time()
            self.sample_count += 1
            self.quickcheck.observe(sample)
            self.sensor_error = None
        return settings

    def snapshot(self, week=None):
        result = self.tracker.snapshot(time.time(), week)
        running = (not self.sensor_stopped_intentionally and (self.native_last_sample is None or time.time() - self.native_last_sample < 20)) if self.native_host else bool(self.sensor and self.sensor.poll() is None)
        result['recording'] = recording_status(self.tracker, time.time(), enabled=self.tracker.setting("capture_enabled", False), running=running, error=self.sensor_error, samples=self.sample_count)
        if result['recording']['state'] == 'starting' and self.sensor_started_at and time.time() - self.sensor_started_at > 10:
            result['recording'].update(state='failed', detail='Mac capture did not return activity. Restart tracking, then check the Mac permission.')
        result.update(version=__version__, sensor_error=self.sensor_error, dreams_connected=bool(self.map), dreams=self.sync.status(), mode="live", quickcheck=self.quickcheck.snapshot(), desktop_context_enabled=self.tracker.setting("desktop_context_enabled", False))
        return result


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "DreamsTime/0.1"

        def log_message(self, format, *args):
            # Request URLs and tokens never enter console logs.
            pass

        def valid_host(self):
            return self.headers.get("Host") in (f"127.0.0.1:{app.port}", f"localhost:{app.port}")

        def allowed_origin(self):
            origin = self.headers.get("Origin", "")
            if not origin or origin in (f"http://127.0.0.1:{app.port}", f"http://localhost:{app.port}"):
                return True
            import re
            return bool(re.fullmatch(r"chrome-extension://[a-p]{32}", origin))

        def authenticated(self):
            supplied = self.headers.get("Authorization", "")
            return self.valid_host() and self.allowed_origin() and hmac.compare_digest(supplied, "Bearer " + app.token)

        def send(self, code, data, content_type="application/json"):
            body = json.dumps(data).encode() if content_type == "application/json" else data.encode() if isinstance(data, str) else data
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            origin = self.headers.get("Origin")
            if origin and self.allowed_origin():
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            if not self.valid_host() or not self.allowed_origin():
                return self.send(403, {"error": "Origin not allowed"})
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", ""))
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()

        def do_GET(self):
            if not self.valid_host():
                return self.send(403, {"error": "Invalid host"})
            path = urlsplit(self.path).path
            if path == "/health":
                return self.send(200, {"app": "dreams-time", "ready": True, "version": __version__, "capture_host": "app" if app.native_host else "standalone"})
            if path == "/oauth/callback":
                try:
                    app.connection.finish(parse_qs(urlsplit(self.path).query))
                    app.sync.refresh()
                    app.tracker.set_setting('sync_error', None)
                    app.tracker.set_setting('weekly_sync', True)
                    app.tracker.set_setting('automatic_sync', True)
                    self.send_response(303)
                    self.send_header('Location', '/signed-in' if app.oauth_native else '/#projects')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                except (ValueError, OSError) as error:
                    app.connection.error = str(error)
                    app.tracker.set_setting('sync_error', str(error))
                    # Never render the authorization code/token from the URL.
                    return self.send(400, 'Dreams connection needs attention. Return to Dreams Time, open Settings, and connect again.', 'text/plain; charset=utf-8')
            if path == '/signed-in':
                return self.send(200, '<!doctype html><html><head><title>Dreams Time is connected</title><link rel="stylesheet" href="/style.css"></head><body><main class="app"><section class="panel"><h1>Hours can now be saved in Dreams.</h1><p>Project hours will save automatically in the background. You can close this page.</p></section></main></body></html>', 'text/html; charset=utf-8')
            if path in ("/", "/app.js", "/style.css"):
                name = "index.html" if path == "/" else path[1:]
                content = (ROOT / "web" / name).read_text()
                if path == "/":
                    content = content.replace("__PAIRING_TOKEN__", app.token)
                return self.send(200, content, {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript", "style.css": "text/css"}[name])
            if not self.authenticated():
                return self.send(401, {"error": "Pair this client with the local tracker."})
            try:
                if path == "/api/snapshot":
                    week = parse_qs(urlsplit(self.path).query).get("week", [None])[0]
                    return self.send(200, app.snapshot(week))
                if path == "/api/selftest":
                    if app.selftest is None:
                        app.selftest = workday()
                    return self.send(200, {k: v for k, v in app.selftest.items() if k != "snapshot"})
                if path == "/api/diagnostics":
                    snap = app.snapshot()
                    return self.send(200, {"version": __version__, "platform": platform.system(), "health": snap["health"], "recording": snap["recording"], "sensor_error": app.sensor_error, "paused": snap["paused"], "rule_count": len(snap["rules"]), "segment_count": len(snap["report"]["segments"]), "test_lab_passed": app.demo["passed"] if app.demo else None})
                return self.send(404, {"error": "Not found"})
            except ValueError as e:
                return self.send(400, {"error": str(e)})

        def do_POST(self):
            if not self.authenticated():
                return self.send(401, {"error": "Pair this client with the local tracker."})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 32 * 1024 * 1024:
                    return self.send(413, {"error": "Choose a JSON file smaller than 32 MB."})
                if self.headers.get_content_type() != "application/json":
                    return self.send(415, {"error": "Expected JSON"})
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Expected a JSON object.")
                path = urlsplit(self.path).path
                if path == "/api/native/sample":
                    if not app.native_host:
                        return self.send(403, {"error": "App-hosted capture is not enabled."})
                    return self.send(200, app.accept_native_sample(data))
                if path == "/api/browser":
                    app.tracker.browser_event(data, time.time())
                    return self.send(200, {"ok": True, "paused": app.tracker.paused})
                if path == "/api/pause":
                    app.tracker.pause(data["paused"])
                    if app.tracker.paused:
                        app.stop_sensor()
                    else:
                        app.start_sensor()
                elif path == "/api/session":
                    app.tracker.assign_session(data["project"], data["app"], data.get("title", ""), time.time())
                elif path == "/api/session/clear":
                    app.tracker.session = None
                    app.tracker.previous = None
                elif path == "/api/settings/desktop-context":
                    if not isinstance(data.get("enabled"), bool):
                        raise ValueError("Expected enabled true or false.")
                    app.tracker.set_setting("desktop_context_enabled", data["enabled"])
                    app.tracker.desktop_context = None
                    app.stop_sensor()
                    app.start_sensor()
                elif path == "/api/projects":
                    app.tracker.add_project(data["name"])
                elif path == "/api/rules":
                    app.tracker.add_rule(data["kind"], data["value"], data["project"], data.get("app", ""))
                elif path == "/api/rules/delete":
                    app.tracker.delete_rule(int(data["id"]))
                elif path == '/api/activity/assign':
                    app.tracker.assign_activity(int(data['id']), data['project'])
                elif path == "/api/review":
                    app.tracker.review(data["week"], data["digest"])
                elif path == "/api/dreams/import":
                    state = data["map"]
                    if not isinstance(state, dict) or not isinstance(state.get("revision"), int) or not isinstance(state.get("edges"), list):
                        raise ValueError("Choose a complete Dreams JSON map export.")
                    count = app.tracker.import_projects(state)
                    app.map = state
                    app.tracker.set_setting("dreams_map", state)
                    return self.send(200, {"projects": count})
                elif path == "/api/dreams/export":
                    state = app.sync.refresh() if app.connection.status()['connected'] else app.map
                    if not state:
                        raise ValueError("Import your current Dreams map to link its project IDs.")
                    report = app.tracker.report(data["week"])
                    return self.send(200, {"tool": "apply_changes", "arguments": build_worked_batch(report, state, app.installation), "note": "Apply via the authenticated Dreams connector. On revision conflict, import a fresh map and prepare again. No remote write has occurred."})
                elif path == '/api/dreams/connect':
                    app.oauth_native = data.get('native') is True
                    return self.send(200, {'url': app.connection.begin()})
                elif path == '/api/dreams/refresh':
                    state = app.sync.refresh()
                    app.tracker.set_setting('sync_error', None)
                    return self.send(200, {'projects': app.tracker.setting('dreams_project_count', 0), 'revision': state['revision']})
                elif path == '/api/dreams/sync':
                    return self.send(200, app.sync.send(data['week']))
                elif path == '/api/dreams/disconnect':
                    app.tracker.set_setting('weekly_sync', False)
                    app.tracker.set_setting('automatic_sync', False)
                    app.connection.disconnect()
                elif path in ('/api/dreams/weekly', '/api/dreams/automatic'):
                    if not isinstance(data.get('enabled'), bool):
                        raise ValueError('Expected enabled true or false.')
                    if data['enabled'] and not app.connection.status()['connected']:
                        raise ValueError('Connect Dreams first.')
                    app.tracker.set_setting('weekly_sync', data['enabled'])
                    app.tracker.set_setting('automatic_sync', data['enabled'])
                elif path == "/api/chatgpt/import":
                    return self.send(200, {"conversations": import_chatgpt(app.tracker, data["conversations"]), "hours_added": 0})
                elif path == "/api/quickcheck":
                    if app.tracker.paused:
                        raise ValueError("Resume tracking first, then run the Mac check.")
                    app.tracker.set_setting("capture_enabled", True)
                    app.start_sensor()
                    app.quickcheck.start()
                    return self.send(200, app.quickcheck.snapshot())
                elif path == "/api/quit":
                    if data.get('restart') is not True:
                        (app.directory / '.stopped').touch(mode=0o600)
                    self.send(200, {"ok": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                elif path == "/api/settings/accessibility":
                    if platform.system() != "Darwin":
                        raise ValueError("This permission is available on a Mac.")
                    subprocess.Popen(["/usr/bin/open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])
                    return self.send(200, {"ok": True})
                elif path == "/api/demo":
                    app.demo = workday()
                    return self.send(200, app.demo)
                elif path == "/api/capture/start":
                    app.tracker.set_setting("capture_enabled", True)
                    app.start_sensor()
                elif path == "/api/sensor/restart":
                    app.stop_sensor()
                    app.start_sensor()
                else:
                    return self.send(404, {"error": "Not found"})
                return self.send(200, {"ok": True})
            except (ValueError, KeyError, TypeError) as e:
                return self.send(400, {"error": str(e)})
    return Handler


def main():
    parser = argparse.ArgumentParser(description="Dreams Time local companion")
    parser.add_argument("--data-dir", default=str(Path.home() / "Library" / "Application Support" / "Dreams Time") if platform.system() == "Darwin" else str(ROOT / ".data"))
    parser.add_argument("--port", type=int, default=43123)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-sensor", action="store_true")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--guided-start", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    app = App(args.data_dir, args.port)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(app))
    except OSError:
        print("Port is already in use. Open the existing tracker at http://127.0.0.1:" + str(args.port), file=sys.stderr)
        raise SystemExit(1)
    if not args.no_sensor:
        app.tracker.set_setting("capture_enabled", True)
        app.start_sensor()
        app.start_watchdog()
    app.sync.start()
    print("Dreams Time → http://127.0.0.1:" + str(args.port), flush=True)
    if not args.no_browser:
        webbrowser.open("http://127.0.0.1:" + str(args.port) + ("/?demo=1" if args.demo else ""))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.sync.stop.set()
        app.watchdog_stop.set()
        if app.watchdog_thread:
            app.watchdog_thread.join(timeout=5)
        if app.sync.thread:
            app.sync.thread.join(timeout=35)
        app.stop_sensor()
        server.server_close()
        app.tracker.close()


if __name__ == "__main__":
    main()
