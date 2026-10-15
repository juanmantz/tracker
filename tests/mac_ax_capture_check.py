"""Prove real macOS window capture in the installed app's own process.

This isolated GitHub-hosted runner is a disposable permission test lab. Test
authorization is provisioned ONLY on CI; this script never ships in the app,
changes customer permissions, or asks customers to run TCC database commands.
"""
import json
import os
import signal
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

assert os.environ.get('CI') == 'true', 'Permission provisioning is CI-only'
APP = Path('/Applications/Dreams Time.app')
SUPPORT = Path.home() / 'Library/Application Support/Dreams Time'
PROOF = Path('artifacts/native-release/ax-capture-check.json')

def api(path, body=None):
    token = (SUPPORT / 'pairing-token').read_text().strip()
    request = Request('http://127.0.0.1:43123'+path,
                      data=None if body is None else json.dumps(body).encode(),
                      headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urlopen(request, timeout=3) as response:
        return json.load(response)

def wait_for(check, timeout=30):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            value=check()
            if value:return value
        except (OSError,ValueError,KeyError,TypeError):
            pass
        time.sleep(.5)
    raise AssertionError('The app did not capture the permitted fixture window')

with tempfile.TemporaryDirectory() as temporary:
    temporary=Path(temporary)
    # First prove the compact update installs over the real installed application.
    subprocess.run(['sudo','/usr/sbin/installer','-pkg','artifacts/native-release/Dreams-Time-Update.pkg','-target','/'],check=True)
    subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(APP)],check=True)
    wait_for(lambda:api('/api/diagnostics')['health'].get('collector'))
    old_pid=api('/api/diagnostics')['health']['collector']['collector_pid']
    os.kill(old_pid,signal.SIGKILL)
    signed=subprocess.run(['/usr/bin/codesign','-d','-r-',str(APP)],capture_output=True,text=True,check=True)
    requirement=signed.stdout+'\n'+signed.stderr
    requirement=next(line.split('designated => ',1)[1] for line in requirement.splitlines() if 'designated => ' in line)
    csreq=temporary/'app.csreq'
    subprocess.run(['/usr/bin/csreq','-r-','-b',str(csreq)],input=requirement,text=True,check=True)
    # Provision the exact signed app requirement in the disposable runner's
    # Accessibility authorization store. No relaxed designated requirement.
    grant_script=temporary/'grant-ci.py'
    grant_script.write_text("""
import sqlite3,sys,time
database,requirement=sys.argv[1:]
db=sqlite3.connect(database)
columns=db.execute('PRAGMA table_info(access)').fetchall()
values={'service':'kTCCServiceAccessibility','client':'local.dreamstime.companion',
        'client_type':0,'auth_value':2,'auth_reason':4,'auth_version':1,
        'csreq':open(requirement,'rb').read(),'policy_id':None,
        'indirect_object_identifier_type':0,'indirect_object_identifier':'UNUSED',
        'indirect_object_code_identity':None,'flags':0,'last_modified':int(time.time()),
        'pid':0,'pid_version':0,'boot_uuid':'UNUSED','last_reminded':0}
keys=[column[1] for column in columns if column[1] in values]
db.execute('DELETE FROM access WHERE service=? AND client=?',
           ('kTCCServiceAccessibility','local.dreamstime.companion'))
db.execute('INSERT INTO access('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+')',
           [values[key] for key in keys])
db.commit()
""")
    python=os.environ.get('pythonLocation')
    python=str(Path(python)/'bin/python3') if python else subprocess.check_output(['/usr/bin/which','python3'],text=True).strip()
    subprocess.run(['sudo',python,str(grant_script),'/Library/Application Support/com.apple.TCC/TCC.db',str(csreq)],check=True)
    subprocess.run(['sudo','/usr/bin/killall','tccd'],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    # Launch via LaunchServices, with the actual app identity used by customers.
    # Intentional SIGKILL can leave a stale LaunchServices registration briefly.
    # Request a fresh instance and retry that transient launch error.
    for attempt in range(20):
        opened=subprocess.run(['/usr/bin/open','-n','-g',str(APP)],capture_output=True,text=True)
        if opened.returncode==0: break
        time.sleep(.5)
    else:
        raise AssertionError('LaunchServices did not reopen the installed app: '+opened.stderr)
    trusted=wait_for(lambda:api('/api/diagnostics')['health'].get('collector',{}).get('ax_trusted'),45)

    fixture=temporary/'WindowFixture.swift'
    fixture.write_text("""
import AppKit
let app=NSApplication.shared
app.setActivationPolicy(.regular)
let menu=NSMenu()
let item=NSMenuItem()
let submenu=NSMenu()
submenu.addItem(withTitle:"Quit",action:#selector(NSApplication.terminate(_:)),keyEquivalent:"q")
item.submenu=submenu;menu.addItem(item);app.mainMenu=menu
let window=NSWindow(contentRect:NSRect(x:100,y:100,width:500,height:300),
                    styleMask:[.titled,.closable],backing:.buffered,defer:false)
window.title="Hey, transform — regression document"
window.makeKeyAndOrderFront(nil)
app.activate(ignoringOtherApps:true)
app.run()
""")
    import plistlib
    fixture_app=temporary/'CI Work App.app'
    executable=fixture_app/'Contents/MacOS/WindowFixture'
    executable.parent.mkdir(parents=True)
    (fixture_app/'Contents/Info.plist').write_bytes(plistlib.dumps({
        'CFBundleIdentifier':'local.dreamstime.fixture','CFBundleExecutable':'WindowFixture',
        'CFBundleName':'CI Work App','CFBundlePackageType':'APPL'}))
    subprocess.run(['/usr/bin/xcrun','swiftc',str(fixture),'-o',str(executable)],check=True)
    subprocess.run(['/usr/bin/codesign','--sign','-','--force',str(fixture_app)],check=True)
    api('/api/pause',{'paused':False})
    process=subprocess.Popen([str(executable)])
    try:
        def captured():
            snapshot=api('/api/snapshot')
            context=(snapshot.get('current')or{}).get('context',{})
            return snapshot if context.get('title')=='Hey, transform — regression document' else None
        snapshot=wait_for(captured)
        collector=snapshot['health']['collector']
        assert collector['collector_bundle']=='local.dreamstime.companion'
        assert collector['collector_pid']!=os.getpid()
        assert collector['window_access_status']=='readable'
        wait_for(lambda:api('/api/snapshot')['recording']['sample_count']>snapshot['recording']['sample_count']+1)
        assert not subprocess.run(['/usr/bin/pgrep','-f','/project/native/activity-sensor'],capture_output=True).stdout
        PROOF.write_text(json.dumps({'compact_update_installed':True,'app_identity':'local.dreamstime.companion',
                                    'accessibility_granted_in_isolated_ci':True,'actual_window_title_read':True,
                                    'permission_probe_and_window_read_agree':True,'separate_sensor_required':False}))
    finally:
        process.terminate();process.wait(timeout=5)
print('Installed app captured a real permitted document title in its own process.')
