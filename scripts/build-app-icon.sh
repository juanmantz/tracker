#!/bin/bash
set -euo pipefail
ICON_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ICON_OUTPUT="$ICON_ROOT/artifacts/app-icon"
ICON_SET="$ICON_OUTPUT/AppIcon.iconset"
mkdir -p "$ICON_SET"
for ICON_SIZE in 16 32 128 256 512; do
  /usr/bin/sips -z "$ICON_SIZE" "$ICON_SIZE" "$ICON_ROOT/native/DreamsTime.png" --out "$ICON_SET/icon_${ICON_SIZE}x${ICON_SIZE}.png" >/dev/null
  ICON_RETINA=$((ICON_SIZE * 2))
  /usr/bin/sips -z "$ICON_RETINA" "$ICON_RETINA" "$ICON_ROOT/native/DreamsTime.png" --out "$ICON_SET/icon_${ICON_SIZE}x${ICON_SIZE}@2x.png" >/dev/null
done
/usr/bin/iconutil -c icns "$ICON_SET" -o "$ICON_ROOT/native/AppIcon.icns"
cp "$ICON_SET/icon_512x512@2x.png" "$ICON_OUTPUT/Dreams-Time-Icon.png"
cp "$ICON_SET/icon_128x128.png" "$ICON_OUTPUT/Dreams-Time-Icon-128.png"
