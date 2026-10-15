"""Real Accessibility UI fixtures; no microphone, camera, messages or account."""
import json
import os
import plistlib
import signal
import sqlite3
import subprocess
import tempfile
import time
import zlib
from pathlib import Path
from urllib.request import Request,urlopen

assert os.environ.get('CI')=='true'
APP=Path('/Applications/Dreams Time.app')
SUPPORT=Path.home()/'Library/Application Support/Dreams Time'
OUT=Path('artifacts/native-release')
def api(path):
    token=(SUPPORT/'pairing-token').read_text().strip()
    with urlopen(Request('http://127.0.0.1:43123'+path,headers={'Authorization':'Bearer '+token}),timeout=3) as response:
        return json.load(response)
def wait_for(check,timeout=35):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            value=check()
            if value:return value
        except (OSError,ValueError,KeyError,TypeError):pass
        time.sleep(.5)
    raise AssertionError('The installed app did not capture the expected compact context')
def gui_pids():
    p=subprocess.run(['/usr/bin/pgrep','-x','DreamsTime'],capture_output=True,text=True)
    return set(p.stdout.split())
def current():return api('/api/snapshot')['current']
def context():return (current() or {}).get('context',{})
def stored(key):
    with sqlite3.connect(SUPPORT/'activity.sqlite') as db:
        row=db.execute('SELECT payload FROM context_snapshots WHERE id=?',(key,)).fetchone()
        return json.loads(zlib.decompress(row[0])) if row else None

with tempfile.TemporaryDirectory() as directory:
    directory=Path(directory)
    source=directory/'ContextFixture.swift'
    source.write_text("""
import AppKit
import Foundation
let app=NSApplication.shared
app.setActivationPolicy(.regular)
let mode=CommandLine.arguments.last ?? "document"
let menu=NSMenu()
let item=NSMenuItem()
let submenu=NSMenu()
submenu.addItem(withTitle:"Quit",action:#selector(NSApplication.terminate(_:)),keyEquivalent:"q")
item.submenu=submenu;menu.addItem(item);app.mainMenu=menu
let window=NSWindow(contentRect:NSRect(x:150,y:150,width:600,height:400),
                    styleMask:[.titled,.closable],backing:.buffered,defer:false)
window.isReleasedWhenClosed=false
window.title=mode=="call" ? "Fixture podcast partner - WhatsApp video call" : "Untitled"
let header=NSTextField(labelWithString:mode=="call" ? "00:03" : "Fixture project 3 - storyboard")
header.frame=NSRect(x:25,y:300,width:500,height:30)
if mode != "call" { header.setAccessibilityIdentifier("document-title");header.setAccessibilityLabel("Document title") }
window.contentView!.addSubview(header)
if mode=="call" {
    let end=NSButton(title:"End call",target:app,action:#selector(NSApplication.terminate(_:)))
    end.frame=NSRect(x:25,y:200,width:150,height:40)
    window.contentView!.addSubview(end)
}
let draft=NSTextField(string:"PRIVATE DRAFT MUST NEVER ENTER SNAPSHOTS")
draft.frame=NSRect(x:25,y:80,width:500,height:30)
window.contentView!.addSubview(draft)
window.makeKeyAndOrderFront(nil)
app.activate(ignoringOtherApps:true)
app.run()
""")
    def launch(name,bundle,mode):
        path=directory/(name+'.app')
        binary=path/'Contents/MacOS/Fixture'
        binary.parent.mkdir(parents=True)
        (path/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':bundle,
            'CFBundleExecutable':'Fixture','CFBundleName':name,'CFBundlePackageType':'APPL'}))
        subprocess.run(['/usr/bin/xcrun','swiftc',str(source),'-o',str(binary)],check=True)
        subprocess.run(['/usr/bin/codesign','--sign','-','--force',str(path)],check=True)
        return subprocess.Popen([str(binary),mode])
    # The production instance lock must also cover direct login-job starts and
    # LaunchServices "new instance" requests, without a second competing sampler.
    original=gui_pids()
    assert len(original)==1,'More than one installed GUI collector is running'
    subprocess.run([str(APP/'Contents/MacOS/DreamsTime'),'--background'],check=True,timeout=10)
    subprocess.run(['/usr/bin/open','-n','-g',str(APP)],check=True)
    time.sleep(2)
    assert gui_pids()==original,'Reopening created a competing collector'
    document=launch('CI Document','local.dreamstime.contextfixture','document')
    try:
        def metadata():
            c=context()
            if c.get('app')!='local.dreamstime.contextfixture' or not c.get('snapshot_id'):return None
            card=stored(c['snapshot_id'])
            return card if card and any('Fixture project 3' in label for label in card['labels']) else None
        card=wait_for(metadata)
        assert 'PRIVATE DRAFT' not in json.dumps(card)
        call=launch('CI Call','net.whatsapp.WhatsApp','call')
        try:
            captured=wait_for(lambda:context() if context().get('activity_kind')=='call' else None)
            session=captured['call_session']
            # Put a different app in front. The connected call remains the sole
            # time owner, with an unchanged opaque session key.
            subprocess.run(['/usr/bin/open','-a','Finder'],check=True)
            time.sleep(5)
            assert context().get('call_session')==session,'Background call was lost'
            assert current()['active'] is True
        finally:
            call.terminate();call.wait(timeout=5)
        wait_for(lambda:context().get('activity_kind')!='call')
        with sqlite3.connect(SUPPORT/'activity.sqlite') as db:
            count,bytes_used=db.execute('SELECT count(*),coalesce(sum(length(payload)+64),0) FROM context_snapshots').fetchone()
        assert count>0 and bytes_used<=1024*1024
        (OUT/'context-check.json').write_text(json.dumps({
            'real_document_header_captured':True,'editable_draft_excluded':True,
            'connected_call_detected':True,'background_call_session_preserved':True,
            'ended_call_stopped':True,'single_collector_after_reopen':True,
            'compressed_snapshot_bytes':bytes_used,'raw_images_stored':False}))
    finally:
        document.terminate();document.wait(timeout=5)
print('Real Mac document headers, background call controls, call end and single-instance capture verified.')
