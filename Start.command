#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3.10 or newer is required. Install it from python.org.' >&2
  read -r -p 'Press Return to close. '
  exit 1
fi
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo 'Python 3.10 or newer is required. Install a current version from python.org.' >&2
  exit 1
fi
if [[ "$(uname -s)" == Darwin && ! -x native/activity-sensor ]]; then
  ./scripts/build-mac.sh
fi
exec python3 -m dreamstime.server
