import json
import random
import tempfile
import unittest
from datetime import datetime, timezone

from dreamstime.account import import_chatgpt
from dreamstime.core import Tracker, identity, clean_url, week_bounds
from dreamstime.dreams import build_batch
from dreamstime.replay import workday, BASE


class Harness:

    def setUp(self):
        self.t = Tracker()
        self.t.add_project("Dreams", "dreams", "remote-dreams")
        self.t.add_project("Client", "client", "remote-client")
        self.t.add_rule("title", "Dreams — Code", "dreams", "editor")

    def tearDown(self):
        self.t.close()

    def sample(self, offset, app="editor", title="Dreams — Code", **extra):
        self.t.ingest({"ts": BASE + offset, "mono": offset, "app": app, "app_name": app, "title": title, "idle": 0, **extra})

    def total(self):
        return self.t.report("2026-10-05")["total_seconds"]

class TrackingTests(Harness, unittest.TestCase):
    def test_switches_credit_previous_activity_not_new_app(self):
        self.sample(0); self.sample(2); self.sample(4, "figma", "Client"); self.sample(6, "figma", "Client")
        self.assertEqual(self.t.report("2026-10-05")["totals"], {"dreams": 4, "unassigned": 2})

    def test_duplicate_and_out_of_order_dont_double_count(self):
        for at in (0, 2, 2, 1, 4): self.sample(at)
        self.assertEqual(self.total(), 4)
        self.assertEqual(self.t.health["rejected"], 2)

    def test_sleep_gap_not_filled(self):
        for at in (0, 2, 3602, 3604): self.sample(at)
        self.assertEqual(self.total(), 4)
        self.assertEqual(self.t.health["gaps"], 1)

    def test_wall_clock_jump_not_filled(self):
        self.sample(0); self.sample(8, mono=2)
        self.assertEqual(self.total(), 0)

    def test_idle_removes_grace_tail(self):
        for at in range(0, 20, 2): self.sample(at)
        for at in range(20, 200, 2): self.sample(at, idle=at-20)
        self.assertEqual(self.total(), 20)
        self.sample(200); self.sample(202)
        self.assertEqual(self.total(), 22)

    def test_lock_and_pause_stop_the_clock(self):
        self.sample(0); self.sample(2); self.sample(4, locked=True); self.sample(6, locked=True)
        self.t.pause(True); self.sample(8); self.sample(10)
        self.t.pause(False); self.sample(12); self.sample(14)
        self.assertEqual(self.total(), 4)

    def test_paused_browser_context_is_not_stored(self):
        self.t.pause(True)
        self.t.browser_event({"focused": True, "url": "https://chatgpt.com/c/private", "capture_context": True, "prompts": ["private"]}, BASE)
        self.assertFalse(self.t.browser)
        self.assertEqual(self.t.db.execute("SELECT count(*) FROM conversations").fetchone()[0], 0)

    def test_background_tab_never_creates_time(self):
        self.t.browser_event({"focused": True, "url": "https://chatgpt.com/c/chat", "title": "Chat"}, BASE)
        self.sample(0); self.sample(2)
        self.assertEqual(self.t.report("2026-10-05")["chatgpt_seconds"], 0)

    def test_browser_context_expires_and_does_not_cross_browsers(self):
        self.t.browser_event({"focused": True, "browser": "chrome", "url": "https://chatgpt.com/c/chat", "title": "Chat"}, BASE)
        self.sample(0, "com.microsoft.edgemac"); self.sample(2, "com.microsoft.edgemac")
        self.assertEqual(self.total(), 0)
        self.sample(10, "com.google.Chrome"); self.sample(12, "com.google.Chrome")
        self.assertEqual(self.total(), 0)

    def test_private_browser_context_excludes_title_and_url(self):
        self.t.browser_event({"focused": True, "private": True, "url": "https://secret.org", "title": "SECRET"}, BASE)
        self.sample(0, "com.google.Chrome", "SECRET"); self.sample(2, "com.google.Chrome", "SECRET")
        self.assertEqual(self.total(), 0)
        self.assertNotIn("SECRET", json.dumps(self.t.snapshot(BASE+2)))

    def test_missing_browser_extension_does_not_capture_private_title(self):
        self.sample(0, "com.google.Chrome", "PRIVATE SECRET"); self.sample(2, "com.google.Chrome", "PRIVATE SECRET")
        self.assertEqual(self.total(), 0)
        self.assertEqual(self.t.current["context"]["title"], "")

    def test_chatgpt_browser_identity_and_usage(self):
        self.t.add_rule("identity", "chatgpt:abc", "dreams")
        self.t.browser_event({"focused": True, "url": "https://chatgpt.com/g/g-custom/c/abc?token=secret", "title": "Working on Dreams"}, BASE)
        self.sample(0, "com.google.Chrome"); self.sample(2, "com.google.Chrome")
        r = self.t.report("2026-10-05")
        self.assertEqual(r["totals"], {"dreams": 2})
        self.assertEqual(r["chatgpt_seconds"], 2)
        self.assertNotIn("secret", json.dumps(r))

    def test_identity_stable_when_figma_name_changes(self):
        self.assertEqual(identity("https://figma.com/design/abc123/Old?node-id=1"), identity("https://www.figma.com/file/abc123/New#secret"))

    def test_untrusted_hosts_cannot_impersonate_chatgpt(self):
        self.assertFalse(identity("https://chatgpt.com.attacker.org/c/abc").startswith("chatgpt:"))
        self.assertFalse(identity("https://figma.com.attacker.org/file/key").startswith("figma:"))
        self.assertEqual(clean_url("https://user:secret@example.org/path?key=secret#secret"), "https://example.org/path")

    def test_mapping_reclassifies_past_time_without_adding_it(self):
        self.sample(0, "figma", "Brand"); self.sample(2, "figma", "Brand")
        self.t.add_rule("title", "Brand", "client", "figma")
        self.assertEqual(self.t.report("2026-10-05")["totals"], {"client": 2})
        self.t.delete_rule(self.t.rules()[-1]["id"])
        self.assertEqual(self.total(), 2)
        self.assertEqual(self.t.report("2026-10-05")["totals"], {"unassigned": 2})

    def test_generic_native_title_needs_explicit_session(self):
        with self.assertRaises(ValueError): self.t.add_rule("title", "ChatGPT", "dreams", "com.openai.chat")
        self.t.assign_session("dreams", "com.openai.chat", "ChatGPT", BASE)
        self.sample(0, "com.openai.chat", "ChatGPT"); self.sample(2, "com.openai.chat", "ChatGPT")
        self.assertEqual(self.t.report("2026-10-05")["totals"], {"dreams": 2})
        self.sample(4, "other", "Other"); self.sample(6, "other", "Other")
        self.assertEqual(self.t.report("2026-10-05")["totals"], {"dreams": 4, "unassigned": 2})
        self.sample(1802, "com.openai.chat", "ChatGPT"); self.sample(1804, "com.openai.chat", "ChatGPT")
        self.assertIsNone(self.t.session)
        self.assertEqual(self.t.report("2026-10-05")["totals"]["dreams"], 4)

    def test_session_survives_rule_reclassification(self):
        self.t.assign_session("dreams", "com.openai.chat", "ChatGPT", BASE)
        self.sample(0, "com.openai.chat", "ChatGPT"); self.sample(2, "com.openai.chat", "ChatGPT")
        self.t.add_rule("title", "Brand", "client", "figma")
        self.assertEqual(self.t.report("2026-10-05")["totals"], {"dreams": 2})

    def test_account_import_deduplicates_and_adds_no_duration(self):
        data = [{"id": "phone-chat", "title": "On my phone", "mapping": {"1": {"message": {"author": {"role": "user"}, "content": {"parts": ["Design the atlas"]}, "create_time": BASE}}}}]
        for _ in range(2): import_chatgpt(self.t, data)
        self.assertEqual(self.t.db.execute("SELECT count(*) FROM conversations").fetchone()[0], 1)
        self.assertEqual(self.total(), 0)

    def test_chat_snippets_require_opt_in(self):
        self.t.browser_event({"focused": True, "url": "https://chatgpt.com/c/abc", "prompts": ["Secret draft"]}, BASE)
        self.assertEqual(self.t.db.execute("SELECT count(*) FROM conversations").fetchone()[0], 0)

    def test_restart_does_not_credit_offline_time(self):
        with tempfile.TemporaryDirectory() as d:
            t = Tracker(d + "/db"); t.ingest({"ts": BASE, "app": "editor"}); t.ingest({"ts": BASE+2, "app": "editor"}); t.close()
            t = Tracker(d + "/db"); t.ingest({"ts": BASE+8, "app": "editor"}); t.ingest({"ts": BASE+10, "app": "editor"})
            self.assertEqual(t.report("2026-10-05")["total_seconds"], 4); t.close()

    def test_dst_weeks_use_local_calendar_boundaries(self):
        start, end = week_bounds("2026-10-19")
        self.assertEqual(end-start, 169*3600)
        start, end = week_bounds("2026-03-23")
        self.assertEqual(end-start, 167*3600)

    def test_cross_week_interval_is_split_not_duplicated(self):
        boundary = week_bounds("2026-10-12")[0]
        self.t.ingest({"ts": boundary-2, "app": "editor"}); self.t.ingest({"ts": boundary+2, "app": "editor"})
        self.assertEqual(self.t.report("2026-10-05")["total_seconds"], 2)
        self.assertEqual(self.t.report("2026-10-12")["total_seconds"], 2)

    def test_review_invalidated_by_activity_or_mapping(self):
        self.sample(0); self.sample(2)
        r = self.t.report("2026-10-05"); self.t.review(r["week"], r["digest"])
        self.assertTrue(self.t.report(r["week"])["reviewed"])
        self.sample(4)
        self.assertFalse(self.t.report(r["week"])["reviewed"])
        with self.assertRaises(ValueError): self.t.review(r["week"], r["digest"])

    def test_bad_numeric_events_rejected(self):
        for ts in (float("nan"), float("inf"), "today", None):
            with self.assertRaises(ValueError): self.t.ingest({"ts": ts, "app": "editor"})

    def test_randomized_no_overlap_and_exact_partition(self):
        rng = random.Random(42)
        offset = 0
        for _ in range(3000):
            offset += rng.choice((2, 2, 2, 30))
            self.sample(offset, rng.choice(("editor", "figma")), locked=rng.random()<.05)
        r = self.t.report("2026-10-05")
        self.assertLessEqual(r["total_seconds"], offset)
        self.assertEqual(sum(r["totals"].values()), sum(s["seconds"] for s in r["segments"]))
        for a, b in zip(r["segments"], r["segments"][1:]): self.assertLessEqual(a["end"], b["start"])

    def test_eight_hours_accelerated_without_touching_live_db(self):
        self.sample(0); self.sample(2)
        before = self.t.report("2026-10-05")
        result = workday()
        self.assertTrue(result["passed"])
        self.assertEqual(self.t.report("2026-10-05"), before)


class DreamsTests(Harness, unittest.TestCase):
    def prepared(self):
        self.sample(0); self.sample(2)
        report = self.t.report("2026-10-05"); self.t.review(report["week"], report["digest"])
        state = {"revision": 12, "nodes": [{"id": "remote-dreams", "kind": "project", "name": "Dreams", "position": {"x": 400, "y": 400}}], "edges": []}
        return self.t.report(report["week"]), state

    def test_dreams_batch_uses_observed_schema_and_no_raw_context(self):
        report, state = self.prepared()
        batch = build_batch(report, state, "device-1")
        node = batch["commands"][0]["node"]
        self.assertEqual(node["fields"]["meaning"], "Hours used")
        self.assertEqual(node["fields"]["basis"], "Confirmed")
        self.assertEqual(node["fields"]["period"], "Custom")
        self.assertNotIn("Dreams — Code", json.dumps(batch))
        self.assertEqual(batch, build_batch(report, state, "device-1"))

    def test_retry_updates_existing_record_preserving_visibility(self):
        report, state = self.prepared()
        b = build_batch(report, state, "device-1")
        node = b["commands"][0]["node"]; node["visible"] = {"amount": False}
        state["nodes"].append(node); state["edges"].append(b["commands"][1]["edge"]); state["revision"] += 1
        retry = build_batch(report, state, "device-1")
        self.assertEqual(len(retry["commands"]), 1)
        self.assertEqual(retry["commands"][0]["type"], "update_node")
        self.assertNotIn("visible", retry["commands"][0]["patch"])

    def test_no_export_until_reviewed_and_linked(self):
        self.sample(0); self.sample(2)
        with self.assertRaises(ValueError): build_batch(self.t.report("2026-10-05"), {"nodes": []}, "device-1")
        report, state = self.prepared()
        state["nodes"] = []
        with self.assertRaises(ValueError): build_batch(report, state, "device-1")

    def test_zero_correction_updates_old_record(self):
        report, state = self.prepared()
        b = build_batch(report, state, "device-1")
        state["nodes"].append(b["commands"][0]["node"]); state["edges"].append(b["commands"][1]["edge"])
        report["totals"] = {}; report["digest"] = "changed"
        correction = build_batch(report, state, "device-1")
        self.assertEqual(correction["commands"][0]["patch"]["fields"]["amount"]["value"], 0)

if __name__ == "__main__": unittest.main()
