#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(uname -s)" != Darwin ]]; then
  echo 'The native sensor builds on macOS. Run Test lab on other systems.' >&2
  exit 1
fi
if ! xcrun --find swiftc >/dev/null 2>&1; then
  echo 'Install Apple Command Line Tools with: xcode-select --install' >&2
  exit 1
fi
xcrun swiftc -parse-as-library -O native/ScreenContext.swift native/ActivitySensor.swift -o native/activity-sensor -framework AppKit -framework ApplicationServices
codesign --force --sign - --identifier local.dreamstime.sensor native/activity-sensor
printf 'Sensor built. Start with: ./Start.command\n'
