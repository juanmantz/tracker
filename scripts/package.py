"""Reproducible source delivery; exclude local history, tokens and installed dependencies."""
import hashlib
import json
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parent.parent
out = root.parent / 'dreams-time-prototype.zip'
allowed_roots = {'dreamstime', 'native', 'extension', 'web', 'scripts', 'tests', 'docs', '.github'}
allowed_files = {'README.md', '.gitignore', 'Start.command', 'Try Demo.command', 'Test.command', 'package.json', 'package-lock.json'}
allowed_artifacts = {'validation.json', 'browser-results.json', 'test-lab-desktop.png', 'test-lab-mobile.png'}
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for path in sorted(root.rglob('*')):
        if not path.is_file(): continue
        rel = path.relative_to(root)
        if '__pycache__' in rel.parts or path.suffix == '.pyc' or path.name == 'activity-sensor': continue
        if rel.parts[0] not in allowed_roots and str(rel) not in allowed_files and not (rel.parts[0] == 'artifacts' and path.name in allowed_artifacts): continue
        z.write(path, Path('Dreams Time') / rel)
with zipfile.ZipFile(out) as z:
    assert z.testzip() is None
    assert not any('/.data/' in n or 'pairing-token' in n or 'activity.sqlite' in n for n in z.namelist())
print(json.dumps({'file': str(out), 'bytes': out.stat().st_size, 'sha256': hashlib.sha256(out.read_bytes()).hexdigest()}))
