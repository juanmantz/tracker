import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from dreamstime.server import App, handler_for


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.app = App(cls.temp.name, 0)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(cls.app))
        cls.app.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); cls.app.tracker.close(); cls.temp.cleanup()

    def request(self, method, path, data=None, token=True, headers=None):
        connection = HTTPConnection("127.0.0.1", self.app.port, timeout=3)
        h = {"Content-Type": "application/json"}
        if token: h["Authorization"] = "Bearer " + self.app.token
        h.update(headers or {})
        connection.request(method, path, body=json.dumps(data) if data is not None else None, headers=h)
        response = connection.getresponse(); status = response.status; body = response.read(); connection.close()
        return status, body

    def test_launcher_health_and_auto_selftest(self):
        status, raw = self.request("GET", "/health", token=False)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["app"], "dreams-time")
        _, before = self.request("GET", "/api/snapshot")
        status, raw = self.request("GET", "/api/selftest")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(raw)["passed"])
        self.assertNotIn("snapshot", json.loads(raw))
        _, after = self.request("GET", "/api/snapshot")
        self.assertEqual(json.loads(before)["report"], json.loads(after)["report"])

    def test_authenticated_reads_and_rejected_unpaired_reads(self):
        self.assertEqual(self.request("GET", "/api/snapshot")[0], 200)
        self.assertEqual(self.request("GET", "/api/snapshot", token=False)[0], 401)

    def test_no_cross_origin_or_dns_rebinding_access(self):
        self.assertEqual(self.request("GET", "/api/snapshot", headers={"Origin": "https://attacker.example"})[0], 401)
        self.assertEqual(self.request("GET", "/", headers={"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/pause", {"paused": True}, headers={"Origin": "null"})[0], 401)

    def test_extension_can_pair_and_browser_context_has_no_independent_clock(self):
        self.assertEqual(self.request("POST", "/api/browser", {"focused": True, "url": "https://chatgpt.com/c/abc"}, headers={"Origin": "chrome-extension://" + "a"*32})[0], 200)
        _, raw = self.request("GET", "/api/snapshot")
        self.assertEqual(json.loads(raw)["report"]["total_seconds"], 0)

    def test_demo_separate_from_live(self):
        _, before = self.request("GET", "/api/snapshot")
        status, replay = self.request("POST", "/api/demo", {})
        self.assertEqual(status, 200); self.assertTrue(json.loads(replay)["passed"])
        _, after = self.request("GET", "/api/snapshot")
        self.assertEqual(json.loads(before)["report"], json.loads(after)["report"])

    def test_pause_validation(self):
        self.assertEqual(self.request("POST", "/api/pause", {"paused": "yes"})[0], 400)
        self.assertEqual(self.request("POST", "/api/pause", {"paused": True})[0], 200)
        self.assertTrue(self.app.tracker.paused)
        self.assertEqual(self.request("POST", "/api/pause", {"paused": False})[0], 200)

    def test_json_only_and_shape_validation(self):
        self.assertEqual(self.request("POST", "/api/projects", {}, headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("POST", "/api/projects", {"name": ""})[0], 400)
        self.assertEqual(self.request("POST", "/api/projects", ["bad shape"])[0], 400)
        self.assertEqual(self.request("GET", "/api/snapshot?week=2026-10-07")[0], 400)

    def test_diagnostics_exclude_sensitive_content(self):
        _, data = self.request("GET", "/api/diagnostics")
        body = json.loads(data)
        self.assertNotIn("conversations", body)
        self.assertNotIn("current", body)
        self.assertNotIn(self.app.token, data.decode())

if __name__ == "__main__": unittest.main()
