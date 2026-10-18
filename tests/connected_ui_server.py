"""Browser workflow fixture: real local app + isolated OAuth/MCP provider."""
import json
import sys
import time
from http.server import ThreadingHTTPServer
from dreamstime.connection import DreamsConnection
from dreamstime.server import App, handler_for
from dreamstime.sync import DreamsSync
from tests.dreams_provider import Provider

provider = Provider()
app = App(sys.argv[1],int(sys.argv[2]))
app.connection = DreamsConnection(sys.argv[1],app.port,provider.origin)
app.sync = DreamsSync(app.tracker,app.connection,app.installation)
now=time.time()-7200
app.tracker.browser_event({'focused':True,'url':'https://chatgpt.com/c/strategyChat','title':'Strategy','capture_context':True,'prompts':['Help with the Birch Client strategy.']},now)
for offset in range(0,7202,2):
    sample={'ts':now+offset,'idle':0,'app':'com.figma.Desktop','app_name':'Figma','title':'Renamed brand file','document':'https://figma.com/design/atlasFile/Renamed'}
    if offset>=3600:
        sample.update(app='com.openai.chat',app_name='ChatGPT',title='Strategy',document='https://chatgpt.com/c/strategyChat')
    if offset>=5400:
        sample.update(title='ChatGPT',document='')
    app.tracker.ingest(sample)
print('ready',flush=True)
try:
    ThreadingHTTPServer(('127.0.0.1',app.port),handler_for(app)).serve_forever()
finally:
    provider.close()
