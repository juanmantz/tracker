"""Verify the installed app's real native icon, including macOS icon lookup."""
import json
import os
import plistlib
import subprocess
import tempfile
from pathlib import Path
assert os.environ.get('CI')=='true'
APP=Path('/Applications/Dreams Time.app')
OUT=Path('artifacts/native-release')
info=plistlib.loads((APP/'Contents/Info.plist').read_bytes())
assert info['CFBundleIconFile']=='AppIcon.icns'
icon=APP/'Contents/Resources'/info['CFBundleIconFile']
assert icon.read_bytes()==Path('native/AppIcon.icns').read_bytes()
assert not (APP/'Icon\r').exists(),'Ship a native bundle icon, not Finder metadata'
subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(APP)],check=True)
with tempfile.TemporaryDirectory() as directory:
    directory=Path(directory)
    source=directory/'IconProbe.swift'
    source.write_text("""
import AppKit
import Foundation
func rendered(_ image:NSImage)->NSBitmapImageRep {
    let bitmap=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:128,pixelsHigh:128,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:bitmap)
    image.draw(in:NSRect(x:0,y:0,width:128,height:128),from:.zero,operation:.copy,fraction:1)
    NSGraphicsContext.restoreGraphicsState()
    return bitmap
}
let app=CommandLine.arguments[1]
let expected=rendered(NSImage(contentsOfFile:CommandLine.arguments[2])!)
let actual=rendered(NSWorkspace.shared.icon(forFile:app))
var difference=0.0
for y in 0..<128 {
    for x in 0..<128 {
        let a=actual.colorAt(x:x,y:y)!.usingColorSpace(.deviceRGB)!
        let b=expected.colorAt(x:x,y:y)!.usingColorSpace(.deviceRGB)!
        difference += Double(abs(a.redComponent-b.redComponent)+abs(a.greenComponent-b.greenComponent)+abs(a.blueComponent-b.blueComponent)+abs(a.alphaComponent-b.alphaComponent))
    }
}
let average=difference/Double(128*128*4)
guard average<0.12 else { fputs("macOS displayed the wrong app icon.\\n",stderr);exit(1) }
try actual.representation(using:.png,properties:[:])!.write(to:URL(fileURLWithPath:CommandLine.arguments[3]))
print("Native app icon matches the generated asset; mean channel difference:",average)
""")
    executable=directory/'icon-probe'
    subprocess.run(['/usr/bin/xcrun','swiftc',str(source),'-o',str(executable)],check=True)
    subprocess.run([str(executable),str(APP),str(icon),str(OUT/'installed-icon.png')],check=True)
proof={'native_icon_registered':True,'macos_icon_lookup_matches_artwork':True,
       'signed_bundle_passes_strict_verification':True,'finder_metadata_patch_used':False,
       'installed_version':info['CFBundleShortVersionString']}
(OUT/'icon-check.json').write_text(json.dumps(proof))
print(json.dumps(proof))
