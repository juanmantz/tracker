#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m unittest discover -s tests -v
python3 - <<'PY'
from dreamstime.replay import workday
r = workday()
for c in r['checks']:
    print(('PASS' if c['passed'] else 'FAIL'), c['name'], ':', c['actual_seconds'], '/', c['expected_seconds'], 'seconds')
print('8 hours replayed in', r['elapsed_ms'], 'ms')
raise SystemExit(0 if r['passed'] else 1)
PY
read -r -p 'Press Return to close. '
