#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
DEMO_DATA_DIR="$(mktemp -d -t dreams-time-demo.XXXXXX)"
trap 'rm -rf "$DEMO_DATA_DIR"' EXIT
python3 -m dreamstime.server --no-sensor --demo --data-dir "$DEMO_DATA_DIR" --port 43124
