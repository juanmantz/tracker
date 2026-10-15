from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo
from .recognition import recognize, WORK_KINDS, normalize, GENERIC

BROWSERS = {"com.google.Chrome", "com.google.Chrome.beta", "com.microsoft.edgemac", "com.brave.Browser", "company.thebrowser.Browser", "com.apple.Safari", "org.mozilla.firefox"}
BROWSER_FAMILIES = {"com.google.Chrome": "chrome", "com.google.Chrome.beta": "chrome", "com.microsoft.edgemac": "edge", "com.brave.Browser": "brave", "company.thebrowser.Browser": "arc"}
EXCLUDED_APPS = {"com.agilebits.onepassword7", "com.1password.1password", "com.apple.loginwindow"}
FOCUS_APPS = {"com.openai.chat", "com.openai.chatgpt", "com.openai.codex", "com.figma.Desktop", "com.microsoft.VSCode", "com.todesktop.230313mzl4w4u92", "com.apple.iWork.Pages", "com.apple.iWork.Keynote", "com.apple.iWork.Numbers", "com.adobe.Photoshop", "com.adobe.illustrator", "com.adobe.InDesign", "com.bohemiancoding.sketch3"}


def clean_url(value):
    """Retain only web origin and path: no credentials, queries, or fragments."""
    if not isinstance(value, str):
        return ""
    try:
        u = urlsplit(value)
        if u.scheme not in ("http", "https") or not u.hostname:
            return ""
        host = u.hostname.lower()
        if host in ("localhost", "127.0.0.1", "::1"):
            return ""
        return urlunsplit((u.scheme, host, u.path[:2048], "", ""))
    except ValueError:
        return ""


def document_identity(value):
    if not isinstance(value, str):
        return "", ""
    if value.startswith("file://"):
        u = urlsplit(value)
        if u.netloc not in ("", "localhost"):
            return "", ""
        safe = urlunsplit(("file", "", u.path[:2048], "", ""))
        return safe, safe
    safe = clean_url(value)
    return safe, identity(safe)


def identity(url):
    u = urlsplit(clean_url(url))
    if u.hostname in ("figma.com", "www.figma.com"):
        match = re.match(r"/(?:file|design|board|slides|proto)/([A-Za-z0-9_-]+)(?:/|$)", u.path)
        if match:
            return "figma:" + match[1]
    if u.hostname in ("chatgpt.com", "chat.openai.com"):
        match = re.search(r"/c/([A-Za-z0-9_-]+)(?:/|$)", u.path)
        if match:
            return "chatgpt:" + match[1]
    return clean_url(url)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def context_key(context):
    # An opaque association key. No URL, path or conversation text leaves the Mac.
    if context.get('identity'):
        return digest(['identity', context['identity']])
    return digest([context.get(k, '') for k in ('app', 'identity', 'title')] +
                  [sorted(h['project'] for h in context.get('project_hints', []) if isinstance(h, dict) and isinstance(h.get('project'), str))])


def rememberable(context):
    if context.get('excluded'):
        return False
    if context.get('identity'):
        return True
    if context.get('app') in ('com.openai.chat', 'com.openai.chatgpt', 'com.openai.codex'):
        return False  # Repeated generic desktop chat titles are not conversation IDs.
    meaningful = set(normalize(context.get('title', '')).split()) - GENERIC - {'untitled', 'draft', 'new', 'window'}
    return bool(meaningful)


def week_bounds(week, tz="Europe/Madrid"):
    day = datetime.strptime(week, "%Y-%m-%d").date()
    if day.weekday() != 0:
        raise ValueError("Choose a Monday for the start of the week.")
    zone = ZoneInfo(tz)
    start = datetime.combine(day, datetime.min.time(), zone)
    end = datetime.combine(day + timedelta(days=7), datetime.min.time(), zone)
    return start.timestamp(), end.timestamp()


def monday(at, tz="Europe/Madrid"):
    day = datetime.fromtimestamp(at, ZoneInfo(tz)).date()
    return (day - timedelta(days=day.weekday())).isoformat()


class Tracker:
    def __init__(self, path=":memory:", idle_after=120, max_gap=10, timezone_name="Europe/Madrid"):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT NOT NULL, dreams_id TEXT);
            CREATE TABLE IF NOT EXISTS rules(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, value TEXT NOT NULL, app TEXT NOT NULL DEFAULT '', project TEXT NOT NULL REFERENCES projects(id), UNIQUE(kind,value,app));
            CREATE TABLE IF NOT EXISTS segments(id INTEGER PRIMARY KEY, start REAL NOT NULL, end REAL NOT NULL, context TEXT NOT NULL, project TEXT, reason TEXT NOT NULL, CHECK(end > start));
            CREATE INDEX IF NOT EXISTS segment_times ON segments(start,end);
            CREATE TABLE IF NOT EXISTS conversations(identity TEXT PRIMARY KEY, title TEXT NOT NULL, prompts TEXT NOT NULL, captured REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS reviews(week TEXT PRIMARY KEY, digest TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        """)
        self.db.commit()
        self.idle_after = idle_after
        self.max_gap = max_gap
        self.timezone = timezone_name
        self.previous = None
        self.browser = {}
        self.current = None
        self.paused = self.setting("paused", False)
        self.health = {"sensor": "waiting", "accessibility": False, "last_sample": None, "gaps": 0, "rejected": 0}
        self.run_start = None
        self.session = None
        self.desktop_context = None

    def setting(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(value)))

    def projects(self):
        with self.lock:
            return [dict(x) for x in self.db.execute("SELECT * FROM projects ORDER BY name")]

    def add_project(self, name, project_id=None, dreams_id=None):
        name = str(name).strip()[:200]
        if not name:
            raise ValueError("Give the project a name.")
        project_id = project_id or "local-" + digest(name)[:16]
        with self.lock, self.db:
            self.db.execute("INSERT INTO projects VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,dreams_id=COALESCE(excluded.dreams_id,projects.dreams_id)", (project_id, name, dreams_id))
        return project_id

    def import_projects(self, state):
        if not isinstance(state, dict):
            raise ValueError("Expected a Dreams map object.")
        nodes = state.get("nodes", [])
        if not isinstance(nodes, list) or len(nodes) > 10000:
            raise ValueError("Expected a Dreams map with a nodes list.")
        candidates = []
        catalog = []
        for n in nodes:
            if not isinstance(n, dict):
                raise ValueError("Invalid node in Dreams map.")
            if n.get("kind") in WORK_KINDS and not n.get("archived"):
                if not isinstance(n.get("id"), str) or not n["id"] or not isinstance(n.get("name"), str) or not n["name"].strip():
                    raise ValueError("Dreams projects need valid IDs and names.")
                candidates.append(n)
                links = n.get("fields", {}).get("links", "")
                if not isinstance(links, str):
                    links = ""
                urls = re.findall(r'https?://[^\s<>"\)]+', links)
                catalog.append({"id":n["id"],"name":n["name"],"kind":n["kind"],"aliases": n['name'].split(' / ') if ' / ' in n['name'] else [],"identities":sorted(set(identity(u.rstrip('.,;')) for u in urls if identity(u.rstrip('.,;'))))})
        count = 0
        for n in candidates:
            if n.get("kind") in WORK_KINDS and not n.get("archived"):
                self.add_project(n["name"], n["id"], n["id"])
                count += 1
        with self.lock:
            if self.setting("recognition_catalog") != catalog:
                self.set_setting("recognition_catalog", catalog)
                self.reclassify()
            self.db.commit()
        return count

    def rules(self):
        with self.lock:
            return [dict(x) for x in self.db.execute("SELECT * FROM rules ORDER BY id")]

    def add_rule(self, kind, value, project, app=""):
        if kind not in ("identity", "title") or not isinstance(value, str) or not value.strip():
            raise ValueError("Choose a specific file, conversation, or window title.")
        if kind == "title" and (not app or value.strip().lower() in ("chatgpt", "figma", "google chrome", "new tab")):
            raise ValueError("This window title is too generic. Use a specific document or browser conversation.")
        with self.lock, self.db:
            if not self.db.execute("SELECT 1 FROM projects WHERE id=?", (project,)).fetchone():
                raise ValueError("Choose an existing project.")
            self.db.execute("INSERT INTO rules(kind,value,app,project) VALUES(?,?,?,?) ON CONFLICT(kind,value,app) DO UPDATE SET project=excluded.project", (kind, value[:2048], app, project))
            self.reclassify()

    def delete_rule(self, rule_id):
        with self.lock, self.db:
            self.db.execute("DELETE FROM rules WHERE id=?", (rule_id,))
            self.reclassify()

    def assign_activity(self, segment_id, project):
        with self.lock, self.db:
            if not self.db.execute('SELECT 1 FROM projects WHERE id=?', (project,)).fetchone():
                raise ValueError('Choose an existing project.')
            if not self.db.execute('SELECT 1 FROM segments WHERE id=?', (segment_id,)).fetchone():
                raise ValueError('This activity no longer exists. Refresh the page.')
            self.db.execute("UPDATE segments SET project=?,reason='Manually assigned activity' WHERE id=?", (project, segment_id))

    def recommendation(self, context, at=None):
        explicit = None
        for kind, value, app in (("identity", context.get("identity", ""), ""), ("title", context.get("title", ""), context.get("app", ""))):
            if value:
                row = self.db.execute("SELECT project FROM rules WHERE kind=? AND value=? AND app=?", (kind, value, app)).fetchone()
                if row:
                    explicit = {"project":row[0],"reason":"Saved file or conversation" if kind == "identity" else "Saved window title"}
                    break
        snippets = []
        if context.get("identity", "").startswith("chatgpt:"):
            row = self.db.execute("SELECT prompts FROM conversations WHERE identity=?", (context["identity"],)).fetchone()
            if row:
                snippets = json.loads(row[0])
        catalog = self.setting("recognition_catalog", [])
        valid = {p['id'] for p in catalog}
        result = recognize(context, catalog, explicit, snippets)
        if context.get('excluded') or explicit:
            return result
        if rememberable(context):
            learned = self.setting('auto_associations', {}).get(context_key(context))
            if learned in valid:
                return {'project': learned, 'confidence': 'reviewed', 'reason': 'Project learned from daily review', 'candidates': []}
        if at is not None:
            key = context_key(context)
            for decision in reversed(self.setting('auto_decisions', [])):
                if decision['context'] == key and decision['start'] <= at < decision['end'] and decision['project'] in valid:
                    return {'project': decision['project'], 'confidence': 'reviewed', 'reason': 'Daily project review', 'candidates': []}
        if result['project'] or result['confidence'] == 'ambiguous':
            return result
        # Only text extracted from a recognized conversation pane can assign by
        # a unique project mention. Whole-window/sidebar text remains a suggestion.
        if context.get('context_scope') == 'conversation' and len(result['candidates']) == 1:
            return {'project': result['candidates'][0]['project'], 'confidence': 'high', 'reason': 'Project in the current conversation', 'candidates': result['candidates']}
        if at is not None and context.get('app') in FOCUS_APPS:
            focus = next((f for f in reversed(self.setting('focus_history', [])) if f['at'] <= at), None)
            if focus and focus['project'] in valid:
                return {'project': focus['project'], 'confidence': 'confirmed', 'reason': 'Current project set in ChatGPT', 'candidates': result['candidates']}
        return result

    def classify(self, context, at=None):
        result = self.recommendation(context, at)
        return result["project"], result["reason"] if result["project"] else ("Excluded activity" if context.get("excluded") else "Needs a project association")

    def reclassify(self):
        boundaries = sorted({f['at'] for f in self.setting('focus_history', [])} |
                            {d[k] for d in self.setting('auto_decisions', []) for k in ('start', 'end')})
        for row in self.db.execute("SELECT * FROM segments").fetchall():
            if row["reason"] in ("Explicit current session", "Manually assigned activity"):
                continue
            context = json.loads(row['context'])
            cuts = [row['start'], *(b for b in boundaries if row['start'] < b < row['end']), row['end']]
            for index, (start, end) in enumerate(zip(cuts, cuts[1:])):
                p, reason = self.classify(context, start)
                if index == 0:
                    self.db.execute("UPDATE segments SET end=?,project=?,reason=? WHERE id=?", (end, p, reason, row['id']))
                else:
                    self.db.execute("INSERT INTO segments(start,end,context,project,reason) VALUES(?,?,?,?,?)", (start,end,row['context'],p,reason))
        if self.current and self.current["reason"] != "Explicit current session":
            self.current["project"], self.current["reason"] = self.classify(self.current["context"], self.current['ts'])
        if self.previous and self.previous["reason"] != "Explicit current session":
            self.previous["project"], self.previous["reason"] = self.classify(self.previous["context"], self.previous['ts'])

    def pause(self, value):
        if not isinstance(value, bool):
            raise ValueError("Pause must be true or false.")
        with self.lock:
            self.paused = value
            self.previous = None
            self.current = None
            self.browser.clear()
            self.session = None
            self.desktop_context = None
            self.set_setting("paused", value)

    def assign_session(self, project, app, title, now):
        with self.lock:
            if not self.db.execute("SELECT 1 FROM projects WHERE id=?", (project,)).fetchone():
                raise ValueError("Choose an existing project.")
            if not isinstance(app, str) or not app or app in BROWSERS or app in EXCLUDED_APPS:
                raise ValueError("Session assignment is for native work apps. Use a browser conversation association instead.")
            self.session = {"app": app, "title": str(title)[:500], "project": project, "expires": now + 1800}
            self.previous = None

    def browser_event(self, event, now):
        family = event.get("browser", "chrome")
        if family not in ("chrome", "edge", "brave", "arc"):
            raise ValueError("Unsupported browser family.")
        with self.lock:
            if self.paused:
                return
            if event.get("private") or not event.get("focused"):
                # Private pages have no title or URL retained.
                self.browser[family] = {"at": now, "excluded": True}
                return
            url = clean_url(event.get("url", ""))
            context = {"at": now, "url": url, "title": str(event.get("title", ""))[:500], "identity": identity(url), "excluded": not bool(url)}
            self.browser[family] = context
            # Capture only submitted user messages explicitly enabled by the extension.
            prompts = event.get("prompts")
            if context["identity"].startswith("chatgpt:") and event.get("capture_context") is True and isinstance(prompts, list):
                prompts = [p[:1000] for p in prompts[-5:] if isinstance(p, str)]
                with self.db:
                    self.db.execute("INSERT OR REPLACE INTO conversations VALUES(?,?,?,?)", (context["identity"], context["title"], json.dumps(prompts), now))

    def context_for(self, sample):
        app = sample.get("app", "")[:200]
        title = sample.get("title", "")[:500]
        context = {"app": app, "app_name": sample.get("app_name", app)[:200], "title": title, "url": "", "identity": "", "source": "window", "excluded": app in EXCLUDED_APPS or not app}
        if app not in BROWSERS and not context["excluded"]:
            document, ident = document_identity(sample.get("document", ""))
            context.update(document=document, identity=ident)
            if document.startswith("http"):
                context["url"] = document
            # Persist only matching project IDs, never accessibility transcript text.
            evidence = sample.get('desktop_context')
            cached = self.desktop_context
            if not evidence and cached and 0 <= sample['ts'] - cached['at'] <= 12 and all(cached.get(key, '') == context.get(key, '') for key in ('app','title','identity')):
                evidence = cached['text']
                context['context_scope'] = cached.get('scope', 'window')
            if evidence and not self.paused:
                context.setdefault('context_scope', sample.get('context_scope', 'window'))
                hints = recognize(context, self.setting("recognition_catalog", []), snippets=[str(evidence)])
                if hints["candidates"]:
                    context["project_hints"] = [{"project":c["project"]} for c in hints["candidates"]]
        if app in BROWSERS:
            # Without fresh extension context, browser activity is deliberately unassigned.
            # A title from an incognito window must not enter history through the native sensor.
            context.update(title="", source="browser context missing")
            family = BROWSER_FAMILIES.get(app)
            b = self.browser.get(family)
            if b and 0 <= sample["ts"] - b["at"] <= 6:
                context.update({k: v for k, v in b.items() if k != "at"})
                context["source"] = "browser"
            else:
                context["excluded"] = True
        if context["excluded"]:
            context.update(title="", url="", identity="", document="")
        return context

    def ingest(self, sample):
        with self.lock:
            return self._ingest(sample)

    def _ingest(self, sample):
        ts, idle = sample.get("ts"), sample.get("idle", 0)
        mono = sample.get("mono", ts)
        if any(not isinstance(v, (float, int)) or isinstance(v, bool) or not math.isfinite(v) for v in (ts, idle, mono)) or idle < 0:
            raise ValueError("Invalid native sample timestamp or idle duration.")
        if self.previous and ts <= self.previous["ts"]:
            self.health["rejected"] += 1
            return False
        if self.run_start is None:
            self.run_start = ts
        context = self.context_for(sample) if not self.paused else {"app": "", "app_name": "Paused", "title": "", "url": "", "identity": "", "source": "paused", "excluded": True}
        project, reason = self.classify(context, ts)
        if self.session:
            if ts >= self.session["expires"] or idle >= self.idle_after or sample.get("locked"):
                self.session = None
            elif self.session["app"] == context["app"] and self.session["title"] == context["title"]:
                project, reason = self.session["project"], "Explicit current session"
        if sample.get("desktop_context") and not self.paused:
            self.desktop_context = {"app": context["app"], "title": context["title"], "identity": context['identity'], "at": ts, "text": str(sample["desktop_context"])[:8000], "scope": sample.get('context_scope', 'window'), "source": "Visible accessibility text"}
        active = not (self.paused or sample.get("locked") or idle >= self.idle_after or context["excluded"])
        current = {"ts": ts, "mono": mono, "idle": idle, "active": active, "context": context, "project": project, "reason": reason}
        prev = self.previous
        with self.db:
            if idle >= self.idle_after:
                # Once idle is confirmed, remove the entire idle tail, including grace time.
                last_input = max(self.run_start, ts - idle)
                self.db.execute("DELETE FROM segments WHERE start>=?", (last_input,))
                self.db.execute("UPDATE segments SET end=? WHERE start<? AND end>?", (last_input, last_input, last_input))
            if prev:
                delta, elapsed = ts - prev["ts"], mono - prev["mono"]
                if delta > self.max_gap or elapsed <= 0 or abs(delta - elapsed) > 3:
                    self.health["gaps"] += 1
                elif prev["active"] and not self.paused and not sample.get("locked"):
                    end = min(ts, ts - idle) if idle >= self.idle_after else ts
                    if end > prev["ts"]:
                        self.add_segment(prev["ts"], end, prev["context"], prev["project"], prev["reason"])
        self.previous = current
        self.current = current
        self.health.update(sensor="connected", accessibility=sample.get("accessibility", False), last_sample=ts)
        self.health["collector"] = {k: sample[k] for k in ("collector_bundle", "collector_pid", "ax_trusted", "window_access_status") if k in sample}
        self.health['input'] = {k: round(sample[k], 1) for k in ('mouse_idle', 'keyboard_idle') if isinstance(sample.get(k), (int, float)) and math.isfinite(sample[k]) and sample[k] >= 0}
        return True

    def add_segment(self, start, end, context, project, reason):
        encoded = json.dumps(context, sort_keys=True)
        last = self.db.execute("SELECT * FROM segments ORDER BY id DESC LIMIT 1").fetchone()
        if last and abs(last["end"] - start) < .001 and last["context"] == encoded and last["project"] == project:
            self.db.execute("UPDATE segments SET end=? WHERE id=?", (end, last["id"]))
        else:
            self.db.execute("INSERT INTO segments(start,end,context,project,reason) VALUES(?,?,?,?,?)", (start, end, encoded, project, reason))

    def segments(self, start, end):
        result = []
        for r in self.db.execute("SELECT * FROM segments WHERE start<? AND end>? ORDER BY start", (end, start)):
            d = dict(r)
            d.update(start=max(r["start"], start), end=min(r["end"], end), context=json.loads(r["context"]))
            d["seconds"] = round(d["end"] - d["start"], 3)
            d["recognition"] = self.recommendation(d["context"], d['start'])
            result.append(d)
        return result

    def report(self, week):
        with self.lock:
            start, end = week_bounds(week, self.timezone)
            segments = self.segments(start, end)
            totals, chatgpt = {}, 0
            for s in segments:
                key = s["project"] or "unassigned"
                totals[key] = totals.get(key, 0) + s["seconds"]
                c = s["context"]
                if c["identity"].startswith("chatgpt:") or c["app"] in ("com.openai.chat", "com.openai.chatgpt", "com.openai.codex") or urlsplit(c["url"]).hostname in ("chatgpt.com", "chat.openai.com"):
                    chatgpt += s["seconds"]
            totals = {k: round(v, 3) for k, v in totals.items()}
            content = {"week": week, "timezone": self.timezone, "totals": totals, "segments": segments, "projects": self.projects()}
            stamp = digest(content)
            review = self.db.execute("SELECT digest FROM reviews WHERE week=?", (week,)).fetchone()
            return {**content, "total_seconds": round(sum(totals.values()), 3), "chatgpt_seconds": round(chatgpt, 3), "digest": stamp, "reviewed": bool(review and review[0] == stamp)}

    def review(self, week, expected_digest):
        with self.lock, self.db:
            report = self.report(week)
            if report["digest"] != expected_digest:
                raise ValueError("Activity changed. Refresh the report before reviewing it.")
            self.db.execute("INSERT OR REPLACE INTO reviews VALUES(?,?)", (week, report["digest"]))
        return report["digest"]

    def snapshot(self, now, week=None):
        with self.lock:
            health = dict(self.health)
            if health["last_sample"] is not None and now - health["last_sample"] > self.max_gap:
                health["sensor"] = "stale"
            return {"health": health, "paused": self.paused, "current": self.current, "report": self.report(week or monday(now, self.timezone)), "rules": self.rules(), "projects": self.projects(), "conversations": [{**dict(r), "prompts": json.loads(r["prompts"])} for r in self.db.execute("SELECT * FROM conversations ORDER BY captured DESC LIMIT 20")], "idle_after": self.idle_after, "session": self.session, "desktop_context": self.desktop_context, "recommendation": self.recommendation(self.current["context"], self.current["ts"]) if self.current else None}

    def close(self):
        self.db.close()
