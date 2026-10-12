// Exercise the real JXA control flow with a Mac API fixture; not a physical Mac test.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';

function sample({bundle='com.openai.chat',title='Dreams discussion',document='',trusted=true,locked=false,idle=0}={}) {
  const written=[]; const focused={attributes:{AXTitle:title,AXDocument:document}};
  const app={bundleIdentifier:bundle,localizedName:'ChatGPT',processIdentifier:123};
  const $ = value => ({dataUsingEncoding:()=>value,dict:value});
  Object.assign($, {
    NSWorkspace:{sharedWorkspace:{frontmostApplication:app}},
    AXIsProcessTrusted:()=>trusted, AXIsProcessTrustedWithOptions:()=>trusted,
    AXUIElementCreateApplication:()=>({attributes:{AXFocusedWindow:focused}}),
    AXUIElementSetMessagingTimeout:()=>0,
    AXUIElementCopyAttributeValue:(element,key,output)=> { if(key.dict in element.attributes){ output[0]=element.attributes[key.dict]; return 0;} return -1; },
    CGSessionCopyCurrentDictionary:()=>({CGSSessionScreenIsLocked:locked}),
    CGEventSourceSecondsSinceLastEventType:()=>idle,
    NSProcessInfo:{processInfo:{systemUptime:102}},
    NSUTF8StringEncoding:4,
    NSFileHandle:{fileHandleWithStandardOutput:{writeData:data=>written.push(data)}},
  });
  const ctx=vm.createContext({$,Ref:()=>[],ObjC:{import:()=>{},unwrap:x=>x,deepUnwrap:x=>x},Date,JSON,Number,Boolean,Math,isFinite,Error});
  vm.runInContext(fs.readFileSync('native/ActivitySensor.js','utf8'),ctx);
  vm.runInContext('run(["--once"])',ctx);
  return JSON.parse(written[0]);
}
test('JXA emits the production native event contract',()=>{
  const s=sample();assert.equal(s.app,'com.openai.chat');assert.equal(s.title,'Dreams discussion');assert.equal(s.idle,0);assert.equal(s.locked,false);assert.equal(s.accessibility,true);
});
test('JXA omits native browser and password-manager titles',()=>{
  assert.equal(sample({bundle:'com.google.Chrome',title:'Private browsing'}).title,'');
  assert.equal(sample({bundle:'com.1password.1password',title:'Password'}).title,'');
});
test('JXA missing accessibility still measures apps',()=>{
  const s=sample({trusted:false});assert.equal(s.app,'com.openai.chat');assert.equal(s.title,'');assert.equal(s.accessibility,false);
});
test('JXA passes screen lock and idle to accounting',()=>{
  const s=sample({locked:true,idle:130});assert.equal(s.locked,true);assert.equal(s.idle,130);
});
test('JXA reads native document identity and excludes browser documents',()=>{
  const document='https://www.figma.com/design/abc/File';
  assert.equal(sample({bundle:'com.figma.Desktop',document}).document,document);
  assert.equal(sample({bundle:'com.google.Chrome',document}).document,'');
});
