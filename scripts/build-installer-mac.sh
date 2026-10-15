#!/bin/bash
set -euo pipefail
BUILD_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_OUTPUT="$BUILD_ROOT/artifacts/native-release"
mkdir -p "$BUILD_OUTPUT/components" "$BUILD_OUTPUT/stage/Applications"
BUILD_SDK="$(/usr/bin/xcrun --show-sdk-path)"
for BUILD_ARCH in arm64 x86_64; do
  /usr/bin/xcrun swiftc -parse-as-library -swift-version 5 -O -sdk "$BUILD_SDK" -target "$BUILD_ARCH-apple-macos12.0" \
    -D DREAMSTIME_APP "$BUILD_ROOT/native/ActivitySensor.swift" "$BUILD_ROOT/native/DreamsTimeApp.swift" -o "$BUILD_OUTPUT/DreamsTime-$BUILD_ARCH"
  /usr/bin/xcrun swiftc -parse-as-library -swift-version 5 -O -sdk "$BUILD_SDK" -target "$BUILD_ARCH-apple-macos12.0" \
    "$BUILD_ROOT/native/ActivitySensor.swift" -o "$BUILD_OUTPUT/sensor-$BUILD_ARCH"
done
/usr/bin/lipo -create "$BUILD_OUTPUT/DreamsTime-arm64" "$BUILD_OUTPUT/DreamsTime-x86_64" -output "$BUILD_OUTPUT/DreamsTime"
/usr/bin/lipo -create "$BUILD_OUTPUT/sensor-arm64" "$BUILD_OUTPUT/sensor-x86_64" -output "$BUILD_OUTPUT/activity-sensor"
/usr/bin/codesign --force --sign - --identifier local.dreamstime.sensor "$BUILD_OUTPUT/activity-sensor"
python3 "$BUILD_ROOT/scripts/package-mac.py" --native-binary "$BUILD_OUTPUT/DreamsTime" --native-sensor "$BUILD_OUTPUT/activity-sensor"
/usr/bin/ditto "$BUILD_ROOT/artifacts/mac-build/Dreams Time.app" "$BUILD_OUTPUT/stage/Applications/Dreams Time.app"
/usr/bin/codesign --force --deep --sign - --identifier local.dreamstime.companion "$BUILD_OUTPUT/stage/Applications/Dreams Time.app"
/usr/bin/codesign --verify --deep --strict "$BUILD_OUTPUT/stage/Applications/Dreams Time.app"
python3 - "$BUILD_OUTPUT/components.plist" <<'PY'
import plistlib, sys
with open(sys.argv[1], 'wb') as f:
    plistlib.dump([{'BundleIsRelocatable':False,'BundleHasStrictIdentifier':True,'BundleIsVersionChecked':True,'RootRelativeBundlePath':'Applications/Dreams Time.app','BundleOverwriteAction':'upgrade'}], f)
PY
chmod +x "$BUILD_ROOT/scripts/pkg/scripts/postinstall"
/usr/bin/pkgbuild --root "$BUILD_OUTPUT/stage" --identifier local.dreamstime.pkg --version 0.8.1 --install-location / \
  --component-plist "$BUILD_OUTPUT/components.plist" --scripts "$BUILD_ROOT/scripts/pkg/scripts" \
  "$BUILD_OUTPUT/components/DreamsTime.pkg"
/usr/bin/productbuild --distribution "$BUILD_ROOT/scripts/pkg/Distribution.xml" --resources "$BUILD_ROOT/scripts/pkg/resources" \
  --package-path "$BUILD_OUTPUT/components" "$BUILD_OUTPUT/Dreams-Time-Installer.pkg"
/usr/sbin/pkgutil --expand "$BUILD_OUTPUT/Dreams-Time-Installer.pkg" "$BUILD_OUTPUT/expanded"
test -f "$BUILD_OUTPUT/expanded/DreamsTime.pkg/Payload"
echo 'Universal Mac app and standard Installer package built.'

# A compact installer for an existing installation. Private runtimes and saved
# activity already live outside the app bundle and survive this replacement.
UPDATE_STAGE="$BUILD_OUTPUT/update-stage"
mkdir -p "$UPDATE_STAGE/Applications"
/usr/bin/ditto "$BUILD_OUTPUT/stage/Applications/Dreams Time.app" "$UPDATE_STAGE/Applications/Dreams Time.app"
rm -rf "$UPDATE_STAGE/Applications/Dreams Time.app/Contents/Resources/runtime"
/usr/bin/codesign --force --deep --sign - --identifier local.dreamstime.companion "$UPDATE_STAGE/Applications/Dreams Time.app"
/usr/bin/codesign --verify --deep --strict "$UPDATE_STAGE/Applications/Dreams Time.app"
/usr/bin/pkgbuild --root "$UPDATE_STAGE" --identifier local.dreamstime.pkg --version 0.8.1 --install-location / \
  --component-plist "$BUILD_OUTPUT/components.plist" --scripts "$BUILD_ROOT/scripts/pkg/scripts" \
  "$BUILD_OUTPUT/Dreams-Time-Update.pkg"
