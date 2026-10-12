"""Test fixture only; production has no event injection endpoint."""
import sys
import time
from http.server import ThreadingHTTPServer
from dreamstime.server import App, handler_for

app = App(sys.argv[1], int(sys.argv[2]))
now = time.time()
app.tracker.ingest({"ts": now-60, "app": "com.openai.chat", "app_name": "ChatGPT", "title": "Dreams planning", "idle": 0})
for offset in range(2, 61, 2):
    app.tracker.ingest({"ts": now-60+offset, "app": "com.openai.chat", "app_name": "ChatGPT", "title": "Dreams planning", "idle": 0})
print("ready", flush=True)
ThreadingHTTPServer(("127.0.0.1", app.port), handler_for(app)).serve_forever()
