"""Read user-provided ChatGPT exports. Message times are evidence, never durations."""
import json
import math


def import_chatgpt(tracker, conversations):
    if not isinstance(conversations, list) or len(conversations) > 50000:
        raise ValueError("Choose conversations.json from your ChatGPT data export.")
    for conv in conversations:
        if not isinstance(conv, dict) or not isinstance(conv.get("mapping", {}), dict):
            raise ValueError("Invalid conversation export structure.")
        for entry in conv.get("mapping", {}).values():
            if not isinstance(entry, dict) or not isinstance(entry.get("message") or {}, dict):
                raise ValueError("Invalid conversation message.")
            message = entry.get("message") or {}
            if not isinstance(message.get("author", {}), dict) or not isinstance(message.get("content", {}), dict):
                raise ValueError("Invalid conversation message fields.")
    count = 0
    with tracker.lock, tracker.db:
        for conv in conversations:
            cid = conv.get("id") or conv.get("conversation_id")
            if not isinstance(cid, str) or not cid or len(cid) > 200:
                continue
            messages = []
            for entry in conv.get("mapping", {}).values():
                m = entry.get("message") or {}
                if m.get("author", {}).get("role") != "user":
                    continue
                ts = m.get("create_time")
                if not isinstance(ts, (float, int)) or not math.isfinite(ts):
                    continue
                parts = m.get("content", {}).get("parts", [])
                text = "\n".join(x for x in parts if isinstance(x, str))[:1000]
                if text:
                    messages.append((ts, text))
            if not messages:
                continue
            messages.sort()
            tracker.db.execute("INSERT INTO conversations VALUES(?,?,?,?) ON CONFLICT(identity) DO UPDATE SET title=excluded.title,prompts=excluded.prompts,captured=excluded.captured WHERE excluded.captured>=conversations.captured", ("chatgpt:" + cid, str(conv.get("title") or "Untitled conversation")[:500], json.dumps([x[1] for x in messages[-5:]]), messages[-1][0]))
            count += 1
    return count
