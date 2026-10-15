"""Install the icon on the exact released app and preserve its working AX grant."""
import hashlib
import json
import os
import plistlib
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request,urlopen
assert os.environ.get('CI') == 'true'
APP=Path('/Applications/Dreams Time.app')
SUPPORT=Path.home()/'Library/Application Support/Dreams Time'
OUT=Path('artifacts/app-icon')
def api(path):
    token=(SUPPORT/'pairing-token').read_text().strip()
    with urlopen(Request('http://127.0.0.1:43123'+path,headers={'Authorization':'Bearer '+token}),timeout=3) as response:
        return json.load(response)
def identity():
    r=subprocess.run(['/usr/bin/codesign','-d','-r-','--verbose=4',str(APP)],capture_output=True,text=True,check=True)
    return '\n'.join(line for line in (r.stdout+'\n'+r.stderr).splitlines() if line.startswith('designated =>') or line.startswith('CDHash='))
def wait_for(check,timeout=30):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            value=check()
            if value:return value
        except (OSError,ValueError,KeyError):pass
        time.sleep(.5)
    raise AssertionError('Installed icon verification timed out')
def fingerprint(path):return hashlib.sha256(path.read_bytes()).hexdigest()
with tempfile.TemporaryDirectory() as temp:
    temp=Path(temp)
    probe=temp/'probe.swift'
    probe.write_text("""
import AppKit
import Foundation
let icon=NSWorkspace.shared.icon(forFile:CommandLine.arguments[1])
guard let data=icon.tiffRepresentation,
      let bitmap=NSBitmapImageRep(data:data),
      let png=bitmap.representation(using:.png,properties:[:]) else { exit(1) }
try png.write(to:URL(fileURLWithPath:CommandLine.arguments[2]))
""")
    binary=temp/'probe'
    subprocess.run(['/usr/bin/xcrun','swiftc',str(probe),'-o',str(binary)],check=True)
    subprocess.run([str(binary),str(APP),str(OUT/'before.png')],check=True)
    before_identity=identity()
    before_contents={str(p.relative_to(APP)):fingerprint(p) for p in APP.rglob('*') if p.is_file()}
    before_pairing=fingerprint(SUPPORT/'pairing-token')
    before_binary=fingerprint(APP/'Contents/MacOS/DreamsTime')
    before_info=fingerprint(APP/'Contents/Info.plist')
    wait_for(lambda:api('/api/diagnostics')['health']['collector'].get('ax_trusted'))
    before_pids=set(subprocess.run(['/usr/bin/pgrep','-x','DreamsTime'],capture_output=True,text=True,check=True).stdout.split())
    for attempt in range(2):
        subprocess.run(['sudo','/usr/sbin/installer','-pkg',str(OUT/'Dreams-Time-Icon.pkg'),'-target','/'],check=True)
        subprocess.run(['/usr/bin/codesign','--verify','--deep',str(APP)],check=True)
        after_contents={str(p.relative_to(APP)):fingerprint(p) for p in APP.rglob('*') if p.is_file() and p.name!='Icon\r'}
        assert after_contents==before_contents,'Icon installation modified signed app contents'
        assert identity()==before_identity,'Icon installation changed the app signing identity'
        assert fingerprint(APP/'Contents/MacOS/DreamsTime')==before_binary
        assert fingerprint(APP/'Contents/Info.plist')==before_info
        assert fingerprint(SUPPORT/'pairing-token')==before_pairing
    time.sleep(4)
    assert api('/api/diagnostics')['health']['collector']['ax_trusted'] is True
    after_pids=set(subprocess.run(['/usr/bin/pgrep','-x','DreamsTime'],capture_output=True,text=True,check=True).stdout.split())
    assert after_pids==before_pids,'Icon installation restarted or created an app process'
    assert str(api('/api/diagnostics')['health']['collector']['collector_pid']) in before_pids
    finder_info=bytes.fromhex(subprocess.run(['/usr/bin/xattr','-px','com.apple.FinderInfo',str(APP)],capture_output=True,text=True,check=True).stdout)
    flags=int.from_bytes(finder_info[8:10],'big')
    assert flags&0x0400,'macOS did not register a custom application icon'
    def changed():
        subprocess.run([str(binary),str(APP),str(OUT/'after.png')],check=True)
        return fingerprint(OUT/'after.png')!=fingerprint(OUT/'before.png')
    wait_for(changed)
    # Also prove authorization survives a later normal application restart.
    subprocess.run(['/bin/launchctl','bootout','gui/'+str(os.getuid())+'/local.dreamstime.start'],capture_output=True)
    for pid in after_pids:
        try:os.kill(int(pid),signal.SIGTERM)
        except ProcessLookupError:pass
    time.sleep(1)
    for attempt in range(20):
        launched=subprocess.run(['/usr/bin/open','-n','-g',str(APP)],capture_output=True,text=True)
        if launched.returncode==0:break
        time.sleep(.5)
    else:raise AssertionError(launched.stderr)
    wait_for(lambda:str(api('/api/diagnostics')['health']['collector']['collector_pid']) not in before_pids and api('/api/diagnostics')['health']['collector']['ax_trusted'])
    # Ensure the normal app packager includes the same icon for future builds.
    subprocess.run([sys.executable,'scripts/package-mac.py','--update-only',
                    '--native-binary',str(APP/'Contents/MacOS/DreamsTime'),
                    '--native-sensor',str(APP/'Contents/Resources/project/native/activity-sensor')],check=True)
    packaged=Path('artifacts/mac-update/Dreams Time.app')
    info=plistlib.loads((packaged/'Contents/Info.plist').read_bytes())
    assert info['CFBundleIconFile']=='AppIcon.icns'
    assert (packaged/'Contents/Resources/AppIcon.icns').read_bytes()==Path('native/AppIcon.icns').read_bytes()
    proof={'finder_icon_changed':True,'application_signature_unchanged':True,'signed_app_contents_unchanged':True,
           'executable_unchanged':True,'info_plist_unchanged':True,'pairing_preserved':True,
           'working_accessibility_grant_preserved':True,'collector_not_restarted':True,
           'second_install_safe':True,'accessibility_preserved_after_normal_reopen':True,'future_app_bundle_icon_included':True}
    (OUT/'icon-check.json').write_text(json.dumps(proof))
    print(json.dumps(proof))
