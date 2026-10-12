"""A virtual clock drives the exact production ingest code: no sleeps, no fake totals."""
from datetime import datetime, timezone
from time import perf_counter
from .core import Tracker, identity, monday

BASE = datetime(2026, 10, 5, 7, tzinfo=timezone.utc).timestamp()


def workday():
    t = Tracker()
    t.add_project("Atlas identity", "atlas", "demo-atlas")
    t.add_project("Dreams companion", "dreams", "demo-dreams")
    t.add_rule("identity", "figma:atlas-file", "atlas")
    t.add_rule("identity", "chatgpt:dreams-chat", "dreams")
    t.add_rule("title", "tracker — Visual Studio Code", "dreams", "com.microsoft.VSCode")
    begin = perf_counter()
    # 09:00–17:00 local: 2h Figma, 30m idle, 1h ChatGPT, 1h away,
    # 2h editor, 1h unassigned research, 30m paused.
    for offset in range(0, 8 * 3600 + 1, 2):
        ts = BASE + offset
        paused = offset >= 27000
        if paused != t.paused:
            t.pause(paused)
        app, name, title, idle, locked = "com.figma.Desktop", "Figma", "Atlas — Figma", 0, False
        if offset < 7200:
            app, name, title = "com.google.Chrome", "Google Chrome", ""
            t.browser_event({"focused": True, "browser": "chrome", "url": "https://www.figma.com/design/atlas-file/Atlas?node-id=9", "title": "Atlas identity — Figma"}, ts)
        elif offset < 9000:
            idle = offset - 7200
        elif offset < 12600:
            app, name = "com.google.Chrome", "Google Chrome"
            t.browser_event({"focused": True, "browser": "chrome", "url": "https://chatgpt.com/c/dreams-chat", "title": "Build a Dreams tracker", "capture_context": True, "prompts": ["How can we test project time without waiting all day?"]}, ts)
        elif offset < 16200:
            locked = True
        elif offset < 23400:
            app, name, title = "com.microsoft.VSCode", "Visual Studio Code", "tracker — Visual Studio Code"
        elif offset < 27000:
            app, name = "com.google.Chrome", "Google Chrome"
            t.browser_event({"focused": True, "browser": "chrome", "url": "https://example.org/research", "title": "Reading about activity tracking"}, ts)
        t.ingest({"ts": ts, "mono": offset, "app": app, "app_name": name, "title": title, "idle": idle, "locked": locked, "accessibility": True})
    # At transitions the sensor samples every two seconds: sleeping/pausing rejects
    # the last unobserved interval conservatively. The exact expected oracle models it.
    report = t.report("2026-10-05")
    expected = {"atlas": 7200, "dreams": 10798, "unassigned": 3598}
    checks = [{"name": k, "expected_seconds": v, "actual_seconds": report["totals"].get(k, 0), "passed": report["totals"].get(k, 0) == v} for k, v in expected.items()]
    checks.append({"name": "ChatGPT foreground only", "expected_seconds": 3598, "actual_seconds": report["chatgpt_seconds"], "passed": report["chatgpt_seconds"] == 3598})
    result = {"name": "Eight-hour workday", "synthetic": True, "elapsed_ms": round((perf_counter() - begin) * 1000), "simulated_hours": 8, "checks": checks, "passed": all(c["passed"] for c in checks), "snapshot": t.snapshot(BASE + 8 * 3600, "2026-10-05")}
    t.close()
    return result
