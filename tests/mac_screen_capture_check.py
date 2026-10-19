"""Real pixels -> local OCR -> project -> measured seconds in disposable macOS CI.

Only this CI fixture provisions permissions. No TCC code ships in the app.
"""
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

assert os.environ.get('CI')=='true', 'Never provision permissions on a customer Mac'
APP=Path('/Applications/Dreams Time.app')
SUPPORT=Path.home()/'Library/Application Support/Dreams Time'
def api(path):
    token=(SUPPORT/'pairing-token').read_text().strip()
    with urlopen(Request('http://127.0.0.1:43123'+path,headers={'Authorization':'Bearer '+token}),timeout=3) as r:return json.load(r)
def wait_for(check,timeout=50):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            result=check()
            if result:return result
        except (OSError,ValueError,KeyError):pass
        time.sleep(.5)
    s=api('/api/snapshot')
    c=(s.get('current')or{}).get('context',{})
    raise AssertionError('Screenshot capture failed: '+json.dumps({'collector':s['health'].get('collector'),'project':(s.get('current')or{}).get('project'),'app':c.get('app'),'hints':c.get('project_hints'),'scope':c.get('context_scope'),'idle':(s.get('current')or{}).get('idle')}))

with tempfile.TemporaryDirectory() as temporary:
    folder=Path(temporary)
    signed=subprocess.run(['/usr/bin/codesign','-d','-r-',str(APP)],capture_output=True,text=True,check=True)
    requirement=next(line.split('designated => ',1)[1] for line in (signed.stdout+'\n'+signed.stderr).splitlines() if 'designated => ' in line)
    csreq=folder/'current.csreq'
    subprocess.run(['/usr/bin/csreq','-r-','-b',str(csreq)],input=requirement,text=True,check=True)
    grant=folder/'permission-ci.py'
    grant.write_text('''import sqlite3,sys,time
database,requirement,client,access,screen=sys.argv[1:]
db=sqlite3.connect(database)
columns=db.execute('PRAGMA table_info(access)').fetchall()
for service,allowed in [('kTCCServiceAccessibility',int(access)),('kTCCServicePostEvent',int(access)),('kTCCServiceScreenCapture',int(screen))]:
 values={'service':service,'client':client,'client_type':0,'auth_value':allowed,'auth_reason':4,'auth_version':1,'csreq':open(requirement,'rb').read(),'policy_id':None,'indirect_object_identifier_type':0,'indirect_object_identifier':'UNUSED','indirect_object_code_identity':None,'flags':0,'last_modified':int(time.time()),'pid':0,'pid_version':0,'boot_uuid':'UNUSED','last_reminded':0}
 keys=[c[1] for c in columns if c[1] in values]
 db.execute('DELETE FROM access WHERE service=? AND client=?',(service,client))
 db.execute('INSERT INTO access('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+')',[values[k] for k in keys])
db.commit()
''')
    python=str(Path(os.environ['pythonLocation'])/'bin/python3')
    pid=api('/api/diagnostics')['health']['collector']['collector_pid']
    assert api('/api/diagnostics')['health']['collector'].get('screen_capture_permission') is False
    # Exercise the same shipped action as the native Allow screen capture button.
    subprocess.run([str(APP/'Contents/MacOS/DreamsTime'),'--screen-access'],check=True)
    wait_for(lambda:api('/api/diagnostics')['health'].get('collector',{}).get('screen_permission_setup')=='settings_open')
    for database in ['/Library/Application Support/com.apple.TCC/TCC.db',str(Path.home()/'Library/Application Support/com.apple.TCC/TCC.db')]:
        subprocess.run(['sudo',python,str(grant),database,str(csreq),'local.dreamstime.companion','0','2'],check=True)
    subprocess.run(['sudo','killall','tccd'],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    # Leaving Settings must refresh the actual collector automatically, with no
    # manual Quit, process kill, timer check or Sync action.
    subprocess.run(['/usr/bin/open','-a','Finder'],check=True)
    wait_for(lambda:(lambda c:c.get('collector_pid')!=pid and c.get('ax_trusted') is False and c.get('screen_capture_permission') is True)(api('/api/diagnostics')['health'].get('collector',{})))
    initial=api('/api/snapshot')['report']['totals'].get('fixture-3',0)
    fixture=folder/'Pixels.swift'
    fixture.write_text('''import AppKit
import ApplicationServices
let app=NSApplication.shared
app.setActivationPolicy(.regular)
let menu=NSMenu(),item=NSMenuItem(),submenu=NSMenu()
submenu.addItem(withTitle:"Quit",action:#selector(NSApplication.terminate(_:)),keyEquivalent:"q")
item.submenu=submenu;menu.addItem(item);app.mainMenu=menu
class Pixels:NSView {
 override func draw(_ rect:NSRect) {
  NSColor.white.setFill();bounds.fill()
  let a:[NSAttributedString.Key:Any]=[.font:NSFont.monospacedSystemFont(ofSize:26,weight:.bold),.foregroundColor:NSColor.black]
  ("Fixture project 7" as NSString).draw(at:NSPoint(x:10,y:420),withAttributes:a)
  ("Fixture project 3" as NSString).draw(at:NSPoint(x:310,y:420),withAttributes:a)
  ("Storyboard work" as NSString).draw(at:NSPoint(x:310,y:350),withAttributes:a)
  ("Fixture project 8 PRIVATE DRAFT" as NSString).draw(at:NSPoint(x:310,y:50),withAttributes:a)
 }
}
let window=NSWindow(contentRect:NSRect(x:120,y:120,width:900,height:600),styleMask:[.titled,.closable],backing:.buffered,defer:false)
window.title="ChatGPT";window.contentView=Pixels(frame:window.contentView!.bounds)
window.makeKeyAndOrderFront(nil);app.activate(ignoringOtherApps:true)
// CI generates real mouse activity only inside its synthetic fixture.
var shifted=false
let timer=Timer.scheduledTimer(withTimeInterval:1,repeats:true){_ in
    // The permission-triggered relaunch finishes asynchronously. Keep the
    // synthetic work window in front while its pixels are being verified.
    window.makeKeyAndOrderFront(nil);app.activate(ignoringOtherApps:true)
    guard AXIsProcessTrusted() && CGPreflightPostEventAccess() else { fputs("CI pixel fixture lacks mouse-event permission.\\n",stderr);exit(2) }
    let source=CGEventSource(stateID:.hidSystemState)
    shifted.toggle()
    CGEvent(mouseEventSource:source,mouseType:.mouseMoved,mouseCursorPosition:CGPoint(x:shifted ? 703 : 697,y:350),mouseButton:.left)?.post(tap:.cghidEventTap)
}
app.run()
''')
    bundle=folder/'PixelFixture.app';executable=bundle/'Contents/MacOS/Pixels'
    executable.parent.mkdir(parents=True)
    (bundle/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.openai.chatgpt','CFBundleExecutable':'Pixels','CFBundleName':'Pixel Fixture','CFBundlePackageType':'APPL'}))
    subprocess.run(['/usr/bin/xcrun','swiftc',str(fixture),'-o',str(executable)],check=True)
    subprocess.run(['/usr/bin/codesign','--sign','-','--force',str(bundle)],check=True)
    fixture_signed=subprocess.run(['/usr/bin/codesign','-d','-r-',str(bundle)],capture_output=True,text=True,check=True)
    fixture_requirement=next(line.split('designated => ',1)[1] for line in (fixture_signed.stdout+'\n'+fixture_signed.stderr).splitlines() if 'designated => ' in line)
    fixture_csreq=folder/'fixture.csreq'
    subprocess.run(['/usr/bin/csreq','-r-','-b',str(fixture_csreq)],input=fixture_requirement,text=True,check=True)
    for database in ['/Library/Application Support/com.apple.TCC/TCC.db',str(Path.home()/'Library/Application Support/com.apple.TCC/TCC.db')]:
        subprocess.run(['sudo',python,str(grant),database,str(fixture_csreq),'com.openai.chatgpt','2','0'],check=True)
    subprocess.run(['sudo','killall','tccd'],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    process=subprocess.Popen([str(executable)])
    try:
        def matched():
            assert process.poll() is None,'The CI mouse-event fixture exited before screenshot attribution'
            s=api('/api/snapshot');c=(s.get('current')or{}).get('context',{})
            return s if (s.get('current')or{}).get('project')=='fixture-3' and c.get('context_scope')=='screenshot' else None
        snapshot=wait_for(matched)
        wait_for(lambda:api('/api/snapshot')['report']['totals'].get('fixture-3',0)>=initial+2)
        c=snapshot['current']['context'];health=snapshot['health']['collector']
        assert health['ax_trusted'] is False and health['screen_capture_permission'] is True
        assert health['screen_capture_count']>=1
        assert health['context_capture_state']=='screen_ocr',health
        with sqlite3.connect(SUPPORT/'activity.sqlite') as db:
            card=json.loads(zlib.decompress(db.execute('SELECT payload FROM context_snapshots WHERE id=?',(c['snapshot_id'],)).fetchone()[0]))
        assert card['source']=='screen_ocr' and card['labels']==['Fixture project 3'],card
        assert 'PRIVATE' not in json.dumps(c) and 'Fixture project 7' not in json.dumps(card)
        Path('artifacts/native-release/screen-capture-check.json').write_text(json.dumps({'real_window_pixels_ocr':True,'works_without_accessibility':True,'screen_permission_required':True,'setup_action_opened_settings':True,'collector_refreshed_automatically_after_setup':True,'sidebar_and_composer_excluded':True,'project':'fixture-3','measured_seconds_added_at_least':2,'images_stored':False,'full_ocr_text_retained':False,'screen_capture_count':health['screen_capture_count']}))
    finally:process.terminate();process.wait(timeout=5)
print('Installed app OCRed real window pixels, excluded sidebar/draft and attributed actual seconds without Accessibility.')
