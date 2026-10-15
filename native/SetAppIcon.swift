// Icon-only maintenance tool. Does not modify signed app contents or permissions.
import AppKit
import Foundation

let arguments = CommandLine.arguments
guard arguments.count == 3 else {
    fputs("Usage: set-app-icon ICON APP\n", stderr)
    exit(2)
}
let iconURL = URL(fileURLWithPath: arguments[1])
let appURL = URL(fileURLWithPath: arguments[2])
guard Bundle(url: appURL)?.bundleIdentifier == "local.dreamstime.companion" else {
    fputs("Dreams Time must already be installed in Applications.\n", stderr)
    exit(1)
}
guard let icon = NSImage(contentsOf: iconURL),
      NSWorkspace.shared.setIcon(icon, forFile: appURL.path, options: []) else {
    fputs("Could not apply the Dreams Time icon.\n", stderr)
    exit(1)
}
NSWorkspace.shared.noteFileSystemChanged(appURL.path)
print("Dreams Time icon installed.")
