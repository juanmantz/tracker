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
mkdir -p "$ICON_OUTPUT/scripts"
for ICON_ARCH in arm64 x86_64; do
  /usr/bin/xcrun swiftc -swift-version 5 -O -target "$ICON_ARCH-apple-macos12.0" "$ICON_ROOT/native/SetAppIcon.swift" -o "$ICON_OUTPUT/set-app-icon-$ICON_ARCH"
done
/usr/bin/lipo -create "$ICON_OUTPUT/set-app-icon-arm64" "$ICON_OUTPUT/set-app-icon-x86_64" -output "$ICON_OUTPUT/scripts/set-app-icon"
/usr/bin/codesign --force --sign - "$ICON_OUTPUT/scripts/set-app-icon"
cp "$ICON_ROOT/native/AppIcon.icns" "$ICON_OUTPUT/scripts/AppIcon.icns"
cp "$ICON_ROOT/scripts/icon-pkg-postinstall" "$ICON_OUTPUT/scripts/postinstall"
chmod 755 "$ICON_OUTPUT/scripts/postinstall" "$ICON_OUTPUT/scripts/set-app-icon"
/usr/bin/pkgbuild --nopayload --identifier local.dreamstime.icon --version 1.0.0 --scripts "$ICON_OUTPUT/scripts" "$ICON_OUTPUT/Dreams-Time-Icon.pkg"
