import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function harness(window) {
  const listeners = {}, requests = [];
  const event = name => ({ addListener(fn) { listeners[name] = fn; } });
  const chrome = {
    storage: { local: { get: async () => ({token:'test-token',browser:'chrome'}), set:async()=>{} } },
    windows: { getLastFocused: async () => window, onFocusChanged:event('focus') },
    tabs: { onActivated:event('tab'), onUpdated:event('updated') },
    runtime: { onMessage:event('message'), onStartup:event('startup'), onInstalled:event('install'), openOptionsPage(){} },
    alarms: { create(){}, onAlarm:event('alarm') },
    action: { setBadgeText:async()=>{}, onClicked:event('clicked') },
  };
  vm.runInNewContext(fs.readFileSync('extension/background.js','utf8'), {
    chrome, AbortSignal, Date, fetch: async (url, options) => { requests.push({url, body:JSON.parse(options.body)}); return {ok:true}; },
  });
  return { requests, async heartbeat(message={},sender={}) { await new Promise(resolve => listeners.message({type:'heartbeat',...message}, sender, resolve)); } };
}
test('only the focused active tab supplies context',async()=>{
  const h=harness({focused:true,tabs:[{id:1,active:false,url:'https://chatgpt.com/c/background'},{id:2,active:true,url:'https://figma.com/design/file/Brand',title:'Brand'}]});
  await h.heartbeat(); assert.equal(h.requests[0].body.url,'https://figma.com/design/file/Brand');
});
test('unfocused browser sends no URL or title',async()=>{
  const h=harness({focused:false,tabs:[{id:1,active:true,url:'https://chatgpt.com/c/background',title:'Private'}]});
  await h.heartbeat(); assert.equal(h.requests[0].body.focused,false); assert.equal(h.requests[0].body.url,undefined);
});
test('late messages from another tab cannot leak conversation text',async()=>{
  const h=harness({focused:true,tabs:[{id:2,active:true,url:'https://chatgpt.com/c/current'}]});
  await h.heartbeat({capture_context:true,prompts:['wrong chat']},{tab:{id:1,url:'https://chatgpt.com/c/old'}});
  assert.equal(h.requests[0].body.prompts,undefined);
});
test('opted-in message text is accepted only from current tab and current URL',async()=>{
  const h=harness({focused:true,tabs:[{id:2,active:true,url:'https://chatgpt.com/c/current'}]});
  await h.heartbeat({capture_context:true,prompts:['submitted prompt']},{tab:{id:2,url:'https://chatgpt.com/c/current'}});
  assert.deepEqual(h.requests[0].body.prompts,['submitted prompt']);
});
test('private tab carries no content',async()=>{
  const h=harness({focused:true,tabs:[{id:1,active:true,incognito:true,url:'https://secret.example',title:'Secret'}]});
  await h.heartbeat(); assert.equal(h.requests[0].body.private,true); assert.equal(h.requests[0].body.url,undefined);
});
test('content reader requests only submitted user messages, never editable inputs',()=>{
  const source=fs.readFileSync('extension/context.js','utf8');
  assert.match(source,/data-message-author-role="user"/);
  assert.doesNotMatch(source,/addEventListener\(['"](?:keydown|input|keyup)/);
  const manifest=JSON.parse(fs.readFileSync('extension/manifest.json','utf8'));
  assert.equal(manifest.incognito,'not_allowed');
});
