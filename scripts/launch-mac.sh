#!/bin/bash
# All tools here ship with macOS. No Homebrew, pip, Xcode or system Python.
set -euo pipefail
umask 077
APP_BUNDLE="${DREAMSTIME_APP_BUNDLE:-$(cd "$(dirname "$0")/../.." && pwd)}"
APP_RESOURCES="$APP_BUNDLE/Contents/Resources"
APP_SUPPORT="${DREAMSTIME_SUPPORT_DIR:-$HOME/Library/Application Support/Dreams Time}"
APP_DESTINATION="${DREAMSTIME_APPLICATIONS_DIR:-$HOME/Applications}/Dreams Time.app"
if [[ "${DREAMSTIME_INSTALLED:-0}" == 1 ]]; then APP_DESTINATION="$APP_BUNDLE"; fi
APP_PORT="${DREAMSTIME_PORT:-43123}"
MAC_OPEN="${DREAMSTIME_OPEN:-/usr/bin/open}"
MAC_OSASCRIPT="${DREAMSTIME_OSASCRIPT:-/usr/bin/osascript}"
MAC_DITTO="${DREAMSTIME_DITTO:-/usr/bin/ditto}"
MAC_TAR="${DREAMSTIME_TAR:-/usr/bin/tar}"
APP_ARCH="${DREAMSTIME_ARCH:-$(uname -m)}"
mkdir -p "$APP_SUPPORT"
APP_LOG="$APP_SUPPORT/launcher.log"
exec >> "$APP_LOG" 2>&1
if [[ "${DREAMSTIME_BACKGROUND:-0}" == 1 ]]; then
  if [[ -e "$APP_SUPPORT/.stopped" ]]; then exit 0; fi
else
  rm -f "$APP_SUPPORT/.stopped"
fi

fail() {
  if [[ "${DREAMSTIME_HEADLESS:-0}" != 1 ]]; then
    "$MAC_OSASCRIPT" -e 'on run argv' -e 'display alert "Dreams Time could not start" message (item 1 of argv) buttons {"OK"} default button "OK"' -e 'end run' "$1" || true
  fi
  exit 1
}
trap 'fail "Setup did not finish. Reopen Dreams Time to retry. The setup log is in Library/Application Support/Dreams Time/launcher.log."' ERR

APP_VERSION="0.8.0"
open_window() {
  if [[ "${DREAMSTIME_HEADLESS:-0}" != 1 ]]; then
    "$MAC_OPEN" "http://127.0.0.1:$APP_PORT/?welcome=1"
  fi
}
# Reuse the same build; replace an older running build before installing this update.
# Previously reopening the new download just reopened the older process forever.
APP_HEALTH="$(/usr/bin/curl --noproxy '*' --silent --max-time 2 "http://127.0.0.1:$APP_PORT/health" || true)"
if [[ "$APP_HEALTH" == *'"app": "dreams-time"'* ]]; then
  if [[ "$APP_HEALTH" == *"\"version\": \"$APP_VERSION\""* ]]; then
    open_window
    exit 0
  fi
  if [[ ! -f "$APP_SUPPORT/pairing-token" ]]; then
    fail "An older tracker is open. Click Quit tracker in its settings, then open this update."
  fi
  APP_PAIRING_TOKEN="$(cat "$APP_SUPPORT/pairing-token")"
  APP_QUIT_STATUS="$(/usr/bin/curl --noproxy '*' --silent --max-time 3 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $APP_PAIRING_TOKEN" -H 'Content-Type: application/json' -d '{"restart":true}' "http://127.0.0.1:$APP_PORT/api/quit")"
  unset APP_PAIRING_TOKEN
  if [[ "$APP_QUIT_STATUS" != 200 ]]; then
    fail "The older tracker could not close. Click Quit tracker in its settings, then open this update."
  fi
  for attempt in {1..25}; do
    if ! /usr/bin/curl --noproxy '*' --silent --max-time 1 "http://127.0.0.1:$APP_PORT/health" >/dev/null; then break; fi
    sleep 0.2
  done
fi

# Serialize first launch so double-clicking twice cannot extract/start two copies.
APP_LOCK="$APP_SUPPORT/.launch-lock"
if ! mkdir "$APP_LOCK" 2>/dev/null; then
  LOCK_OWNER="$(cat "$APP_LOCK/pid" 2>/dev/null || true)"
  if [[ "$LOCK_OWNER" =~ ^[0-9]+$ ]] && kill -0 "$LOCK_OWNER" 2>/dev/null; then
    for attempt in {1..150}; do
      APP_HEALTH="$(/usr/bin/curl --noproxy '*' --silent --max-time 1 "http://127.0.0.1:$APP_PORT/health" || true)"
      if [[ "$APP_HEALTH" == *"\"version\": \"$APP_VERSION\""* ]]; then open_window; exit 0; fi
      if ! kill -0 "$LOCK_OWNER" 2>/dev/null; then break; fi
      sleep 0.2
    done
    fail "Another launch did not finish. Reopen Dreams Time to retry."
  fi
  rm -rf "$APP_LOCK"
  mkdir "$APP_LOCK"
fi
printf '%s\n' "$$" > "$APP_LOCK/pid"
cleanup() { rm -rf "$APP_LOCK"; }
trap cleanup EXIT

# Install in your user Applications folder, including from Downloads or a read-only disk.
if [[ "$APP_BUNDLE" != "$APP_DESTINATION" ]]; then
  mkdir -p "$(dirname "$APP_DESTINATION")"
  APP_COPY="$APP_DESTINATION.installing-$$"
  "$MAC_DITTO" "$APP_BUNDLE" "$APP_COPY"
  if [[ -e "$APP_DESTINATION" ]]; then
    APP_OLD="$APP_DESTINATION.previous-$$"
    mv "$APP_DESTINATION" "$APP_OLD"
  fi
  mv "$APP_COPY" "$APP_DESTINATION"
  if [[ -n "${APP_OLD:-}" ]]; then rm -rf "$APP_OLD"; fi
  APP_BUNDLE="$APP_DESTINATION"
  APP_RESOURCES="$APP_BUNDLE/Contents/Resources"
fi

case "$APP_ARCH" in
  arm64|aarch64) RUNTIME_ARCH="arm64"; RUNTIME_SHA="233f8e15255b3e1d1fd47ea5dd5230dfed803f371138e896e54d98c60ae19f6f" ;;
  x86_64) RUNTIME_ARCH="intel"; RUNTIME_SHA="fb3187d95334813b88940db0f1ca57b84cedfd552739c3a5771c3ea0e49988c9" ;;
  *) fail "This download supports Apple Silicon and Intel Macs." ;;
esac
RUNTIME_DIR="$APP_SUPPORT/runtime-3.12.15-$RUNTIME_ARCH"
RUNTIME_PYTHON="$RUNTIME_DIR/python/bin/python3"
if [[ ! -x "$RUNTIME_PYTHON" ]]; then
  RUNTIME_ARCHIVE="$APP_RESOURCES/runtime/$RUNTIME_ARCH.tar.gz"
  if [[ ! -f "$RUNTIME_ARCHIVE" ]]; then fail "The app download is incomplete. Download the Mac app again."; fi
  printf '%s  %s\n' "$RUNTIME_SHA" "$RUNTIME_ARCHIVE" | /usr/bin/shasum -a 256 -c -
  RUNTIME_STAGE="$(mktemp -d "$APP_SUPPORT/.runtime.XXXXXX")"
  "$MAC_TAR" -xzf "$RUNTIME_ARCHIVE" -C "$RUNTIME_STAGE"
  "$RUNTIME_STAGE/python/bin/python3" -I -c 'import sys, sqlite3, zoneinfo; assert sys.version_info >= (3, 10); zoneinfo.ZoneInfo("Europe/Madrid")'
  mv "$RUNTIME_STAGE" "$RUNTIME_DIR"
fi
cd "$APP_RESOURCES/project"
# Start detached: closing the browser or relaunching the app keeps one collector.
/usr/bin/nohup "$RUNTIME_PYTHON" -m dreamstime.server --port "$APP_PORT" --data-dir "$APP_SUPPORT" --no-browser > "$APP_SUPPORT/tracker.log" 2>&1 < /dev/null &
APP_PID=$!
printf '%s\n' "$APP_PID" > "$APP_SUPPORT/tracker.pid"
# Bounded readiness polling. Opens only after the app can serve its self-test.
for attempt in {1..50}; do
  if /usr/bin/curl --noproxy '*' --silent --max-time 1 "http://127.0.0.1:$APP_PORT/health" | /usr/bin/grep -Fq '"app": "dreams-time"'; then
    open_window
    exit 0
  fi
  if ! kill -0 "$APP_PID" 2>/dev/null; then
    fail "The tracker stopped during startup. Reopen the app to retry. The log is in Library/Application Support/Dreams Time/tracker.log."
  fi
  sleep 0.2
done
fail "The tracker did not become ready. Another app may be using port 43123."
