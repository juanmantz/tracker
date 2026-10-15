"""Reproduce stale Accessibility identity after a real unsigned app upgrade.
Only runs on disposable macOS CI. Never ships in the installed application.
"""
import json, os, signal, subprocess, sys, tempfile, time
from pathlib import Path
from urllib.request import Request, urlopen
assert os.environ.get('CI') == 'true'
OUT=Path('artifacts/native-release')
OUT.mkdir(parents=True,exist_ok=True)
APP=Path('/Applications/Dreams Time.app')
SUPPORT=Path.home()/'Library/Application Support/Dreams Time'

def requirement(app):
    signed=subprocess.run(['/usr/bin/codesign','-d','-r-',str(app)],capture_output=True,text=True,check=True)
    return next(line.split('designated => ',1)[1] for line in (signed.stdout+'\n'+signed.stderr).splitlines() if 'designated => ' in line)

def api(path):
    token=(SUPPORT/'pairing-token').read_text().strip()
    with urlopen(Request('http://127.0.0.1:43123'+path,headers={'Authorization':'Bearer '+token}),timeout=3) as response:
        return json.load(response)

def wait_for(check,timeout=40):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            value=check()
            if value:return value
        except (OSError,ValueError,KeyError,TypeError):
            pass
        time.sleep(.5)
    raise AssertionError('macOS identity fixture timed out')

def gui_pids():
    found=subprocess.run(['/usr/bin/pgrep','-x','DreamsTime'],capture_output=True,text=True)
    return [int(x) for x in found.stdout.split()]

with tempfile.TemporaryDirectory() as directory:
    directory=Path(directory)
    subprocess.run(['/usr/sbin/pkgutil','--expand-full','artifacts/native-release/Previous-Update.pkg',str(directory/'previous')],check=True)
    previous=next((directory/'previous').rglob('Dreams Time.app'))
    old_requirement=requirement(previous)
    subprocess.run(['sudo','/usr/sbin/installer','-pkg','artifacts/native-release/Dreams-Time-Installer.pkg','-target','/'],check=True)
    wait_for(lambda:api('/api/diagnostics')['health'].get('collector'))
    current_requirement=requirement(APP)
    assert old_requirement!=current_requirement,'The fixture must use different version-bound identities'
    time.sleep(3)
    installed_pids=gui_pids()
    print('Installer-created GUI process count:',len(installed_pids),flush=True)

    subprocess.run(['/bin/launchctl','bootout','gui/'+str(os.getuid())+'/local.dreamstime.start'],check=False,capture_output=True)
    for pid in gui_pids():
        try:os.kill(pid,signal.SIGTERM)
        except ProcessLookupError:pass
    time.sleep(1)
    csreq=directory/'old.csreq'
    subprocess.run(['/usr/bin/csreq','-r-','-b',str(csreq)],input=old_requirement,text=True,check=True)
    grant=directory/'grant-old.py'
    grant.write_text("""
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
db.execute('DELETE FROM access WHERE service=? AND client=?',('kTCCServiceAccessibility','local.dreamstime.companion'))
db.execute('INSERT INTO access('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+')',[values[key] for key in keys])
db.commit()
""")
    subprocess.run(['sudo',sys.executable,str(grant),'/Library/Application Support/com.apple.TCC/TCC.db',str(csreq)],check=True)
    subprocess.run(['sudo','/usr/bin/killall','tccd'],check=False,capture_output=True)
    previous_pid=api('/api/diagnostics')['health']['collector']['collector_pid']
    for attempt in range(20):
        launched=subprocess.run(['/usr/bin/open','-n','-g',str(APP)],capture_output=True,text=True)
        if launched.returncode==0:break
        time.sleep(.5)
    else:raise AssertionError(launched.stderr)
    collector=wait_for(lambda: (c if (c:=api('/api/diagnostics')['health'].get('collector',{})).get('collector_pid')!=previous_pid else None))
    assert collector['collector_bundle']=='local.dreamstime.companion'
    assert collector['ax_trusted'] is False
    print('An enabled grant for 0.8.0 does not authorize 0.8.1:',json.dumps(collector),flush=True)
    # Existing real-window test grants the current exact signed requirement and
    # then checks a real separate application window. No customer data or account.
    subprocess.run([sys.executable,'tests/mac_ax_capture_check.py'],check=True)
    proof=json.loads((OUT/'ax-capture-check.json').read_text())
    assert proof['actual_window_title_read'] is True
    proof.update({'previous_and_current_identities_differ':True,
                  'enabled_previous_identity_does_not_authorize_update':True,
                  'fresh_current_identity_grant_restores_real_document_capture':True,
                  'installer_created_gui_processes':len(installed_pids)})
    (OUT/'permission-identity-check.json').write_text(json.dumps(proof))
    print(json.dumps(proof),flush=True)
