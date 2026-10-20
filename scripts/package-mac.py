"""Build one offline universal .app, preserving executable permissions in its ZIP."""
import argparse
import hashlib
import json
import os
import plistlib
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--update-only', action='store_true')
parser.add_argument('--native-binary', type=Path)
parser.add_argument('--native-sensor', type=Path)
args = parser.parse_args()
BUILD = ROOT / 'artifacts' / ('mac-update' if args.update_only else 'mac-build')
APP = BUILD / 'Dreams Time.app'
RESOURCES = APP / 'Contents' / 'Resources'
EXPECTED = {'arm64': '233f8e15255b3e1d1fd47ea5dd5230dfed803f371138e896e54d98c60ae19f6f', 'intel': 'fb3187d95334813b88940db0f1ca57b84cedfd552739c3a5771c3ea0e49988c9'}
RUNTIMES = {'arm64': Path('/tmp/dreamstime-arm64.tar.gz'), 'intel': Path('/tmp/dreamstime-intel.tar.gz')}
if APP.exists(): shutil.rmtree(APP)
(RESOURCES / 'runtime').mkdir(parents=True)
for arch, source in ([] if args.update_only else RUNTIMES.items()):
    assert hashlib.sha256(source.read_bytes()).hexdigest() == EXPECTED[arch], 'Runtime checksum mismatch'
    shutil.copyfile(source, RESOURCES / 'runtime' / (arch + '.tar.gz'))
for directory in ('dreamstime', 'native', 'web', 'extension'):
    shutil.copytree(ROOT / directory, RESOURCES / 'project' / directory, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'activity-sensor', 'DreamsTime.png', 'AppIcon.icns'))
sensor_binary = RESOURCES / 'project' / 'native' / 'activity-sensor'
if args.native_sensor:
    shutil.copyfile(args.native_sensor, sensor_binary)
executable = APP / 'Contents' / 'MacOS' / 'DreamsTime'
executable.parent.mkdir()
shutil.copyfile(args.native_binary or ROOT / 'scripts' / 'launch-mac.sh', executable)
if args.native_binary:
    shutil.copyfile(ROOT / 'scripts' / 'launch-mac.sh', RESOURCES / 'launch-mac.sh')
executable.chmod(0o755)
icon_source = ROOT / 'native' / 'AppIcon.icns'
if icon_source.exists():
    shutil.copyfile(icon_source, RESOURCES / 'AppIcon.icns')
info = {'CFBundleName':'Dreams Time', 'CFBundleDisplayName':'Dreams Time', 'CFBundleIdentifier':'local.dreamstime.companion',
        'CFBundleExecutable':'DreamsTime', 'CFBundlePackageType':'APPL', 'CFBundleShortVersionString':'0.12.0',
        'CFBundleVersion':'17', 'LSUIElement':not bool(args.native_binary), 'LSMinimumSystemVersion':'12.0', 'NSHighResolutionCapable':True,
        'NSAccessibilityUsageDescription':'Dreams Time reads the active document name to identify the project you are working on.',
        'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True}}
if icon_source.exists():
    info['CFBundleIconFile'] = 'AppIcon.icns'
(APP / 'Contents' / 'Info.plist').write_bytes(plistlib.dumps(info))
(APP / 'Contents' / 'PkgInfo').write_bytes(b'APPL????')
# All distributable app resources readable; entry point executable after Finder extraction.
for p in APP.rglob('*'):
    if p.is_file() and p not in (executable, sensor_binary): p.chmod(0o644)
    elif p == sensor_binary: p.chmod(0o755)
    elif p.is_dir(): p.chmod(0o755)
APP.chmod(0o755)
readme = BUILD / 'OPEN FIRST.txt'
readme.write_text(("Small update for an already installed Dreams Time Mac app. Reuses its installed private runtime.\n\n" if args.update_only else "") + """1. Unzip.
2. Open Dreams Time.app.

Your existing tracking data and settings are kept. The old running version is replaced.
If already connected to Dreams, your sign-in is preserved. Otherwise connect once in Projects.
Project matching and completed-hour saving run automatically, including the current week.
The update rechecks old inferred assignments without deleting measured time.
Projects > What counted shows the documents, apps and reasons behind each total.

If macOS blocks the unsigned app, use Privacy & Security > Open Anyway.
Python, Homebrew and Xcode are not needed. A browser companion is needed only for browser activity.
The app installs in your user Applications folder. Your activity remains on your Mac.

The app is ad-hoc signed and is not notarized. Releases are gated by installed-app tests on a macOS runner.
""")
OUT = ROOT.parent / ('Dreams-Time-Update-0.12.0.zip' if args.update_only else 'Dreams-Time-Mac-0.12.0.zip')
with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
    for p in sorted(APP.rglob('*')):
        archive.write(p, p.relative_to(BUILD))
    archive.write(readme, readme.name)
with zipfile.ZipFile(OUT) as archive:
    assert archive.testzip() is None
    mode = archive.getinfo('Dreams Time.app/Contents/MacOS/DreamsTime').external_attr >> 16
    assert mode & 0o111
    assert not any('activity.sqlite' in p or 'pairing-token' in p for p in archive.namelist())
print(json.dumps({'file':str(OUT),'bytes':OUT.stat().st_size,'update_only':args.update_only,'version':'0.12.0'}))
