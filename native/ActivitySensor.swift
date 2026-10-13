// macOS-only foreground sensor. Never captures keystrokes or screenshots.
import AppKit
import ApplicationServices
import Foundation

let prompt = CommandLine.arguments.contains("--request-permission")
if prompt {
    let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
    _ = AXIsProcessTrustedWithOptions(options)
}
var sessionActive = true
var awake = true
let center = NSWorkspace.shared.notificationCenter
let observers = [
    center.addObserver(forName: NSWorkspace.sessionDidResignActiveNotification, object: nil, queue: .main) { _ in sessionActive = false },
    center.addObserver(forName: NSWorkspace.sessionDidBecomeActiveNotification, object: nil, queue: .main) { _ in sessionActive = true },
    center.addObserver(forName: NSWorkspace.willSleepNotification, object: nil, queue: .main) { _ in awake = false },
    center.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { _ in awake = true }
]

let contextEnabled = CommandLine.arguments.contains("--chatgpt-context")
var lastContextAt = 0.0
// Only promote text from an explicitly identified conversation/main region.
// A whole-window scan may contain unrelated chats in the sidebar.
func conversationPane(_ root: AXUIElement) -> AXUIElement? {
    var queue: [AXUIElement] = [root]
    let deadline = Date().timeIntervalSince1970 + 0.15
    var visited = 0
    while !queue.isEmpty && visited < 80 && Date().timeIntervalSince1970 < deadline {
        let node = queue.removeFirst()
        visited += 1
        AXUIElementSetMessagingTimeout(node, 0.04)
        var roleValue: CFTypeRef?
        _ = AXUIElementCopyAttributeValue(node, kAXRoleAttribute as CFString, &roleValue)
        let role = roleValue as? String ?? ""
        if ["AXTextField", "AXTextArea", "AXSecureTextField", "AXComboBox", "AXOutline", "AXToolbar"].contains(role) { continue }
        var subrole: CFTypeRef?
        _ = AXUIElementCopyAttributeValue(node, kAXSubroleAttribute as CFString, &subrole)
        if subrole as? String == "AXLandmarkMain" { return node }
        var description: CFTypeRef?
        _ = AXUIElementCopyAttributeValue(node, kAXDescriptionAttribute as CFString, &description)
        if ["AXScrollArea", "AXGroup"].contains(role),
           ["conversation", "chat messages", "main content"].contains((description as? String ?? "").lowercased()) { return node }
        var children: CFTypeRef?
        _ = AXUIElementCopyAttributeValue(node, kAXChildrenAttribute as CFString, &children)
        if let elements = children as? [AXUIElement] { queue.append(contentsOf: elements.prefix(30)) }
    }
    return nil
}
func visibleText(_ root: AXUIElement) -> String {
    var queue: [(AXUIElement, Int)] = [(root, 0)]
    var output: [String] = []
    let deadline = Date().timeIntervalSince1970 + 0.3
    var visited = 0
    while !queue.isEmpty && visited < 160 && Date().timeIntervalSince1970 < deadline {
        let (node, depth) = queue.removeFirst()
        visited += 1
        AXUIElementSetMessagingTimeout(node, 0.08)
        var roleValue: CFTypeRef?
        _ = AXUIElementCopyAttributeValue(node, kAXRoleAttribute as CFString, &roleValue)
        let role = roleValue as? String ?? ""
        // Do not traverse editable controls: drafts never become context.
        if ["AXTextField", "AXTextArea", "AXSecureTextField", "AXComboBox", "AXOutline", "AXToolbar"].contains(role) { continue }
        if role == "AXStaticText" {
            var value: CFTypeRef?
            _ = AXUIElementCopyAttributeValue(node, kAXValueAttribute as CFString, &value)
            if let text = value as? String, !text.isEmpty { output.append(String(text.prefix(1000))) }
        }
        if depth < 8 {
            var children: CFTypeRef?
            _ = AXUIElementCopyAttributeValue(node, kAXChildrenAttribute as CFString, &children)
            if let elements = children as? [AXUIElement] {
                queue.append(contentsOf: elements.prefix(40).map { ($0, depth + 1) })
            }
        }
    }
    return String(output.joined(separator: "\n").prefix(8000))
}

func emit() {
    let app = NSWorkspace.shared.frontmostApplication
    let trusted = AXIsProcessTrusted()
    var title = ""
    var document = ""
    var contextText = ""
    var contextScope = "window"
    let bundle = app?.bundleIdentifier ?? ""
    // Browser titles are supplied by the extension, which can exclude private tabs.
    let browsers: Set<String> = ["com.google.Chrome", "com.google.Chrome.beta", "com.microsoft.edgemac", "com.brave.Browser", "company.thebrowser.Browser", "com.apple.Safari", "org.mozilla.firefox"]
    let excluded: Set<String> = ["com.agilebits.onepassword7", "com.1password.1password", "com.apple.loginwindow"]
    if trusted, let pid = app?.processIdentifier, !browsers.contains(bundle), !excluded.contains(bundle) {
        let element = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(element, 0.4)
        var window: CFTypeRef?
        if AXUIElementCopyAttributeValue(element, kAXFocusedWindowAttribute as CFString, &window) == .success,
           let window = window, CFGetTypeID(window) == AXUIElementGetTypeID() {
            var value: CFTypeRef?
            let axWindow = unsafeBitCast(window, to: AXUIElement.self)
            if AXUIElementCopyAttributeValue(axWindow, kAXTitleAttribute as CFString, &value) == .success {
                title = value as? String ?? ""
            }
            var documentValue: CFTypeRef?
            if AXUIElementCopyAttributeValue(axWindow, kAXDocumentAttribute as CFString, &documentValue) == .success {
                document = documentValue as? String ?? (documentValue as? URL)?.absoluteString ?? ""
            }
            if contextEnabled && ["com.openai.chat", "com.openai.chatgpt", "com.openai.codex"].contains(bundle) && Date().timeIntervalSince1970 - lastContextAt > 10 {
                if let pane = conversationPane(axWindow) {
                    contextText = visibleText(pane)
                    contextScope = "conversation"
                } else { contextText = visibleText(axWindow) }
                lastContextAt = Date().timeIntervalSince1970
            }
        }
    }
    let session = CGSessionCopyCurrentDictionary() as? [String: Any]
    let locked = session == nil || !sessionActive || !awake || (session?["CGSSessionScreenIsLocked"] as? Bool ?? false) || (session?["kCGSSessionOnConsoleKey"] as? Bool == false) || bundle == "com.apple.loginwindow"
    let idle = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: CGEventType(rawValue: UInt32.max)!)
    guard idle.isFinite && idle >= 0 else { fputs("macOS returned an invalid idle duration.\n", stderr); exit(1) }
    let mouseTypes: [CGEventType] = [.mouseMoved, .leftMouseDragged, .rightMouseDragged, .otherMouseDragged, .leftMouseDown, .rightMouseDown, .otherMouseDown, .scrollWheel]
    let mouseIdle = mouseTypes.map { CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: $0) }.min() ?? idle
    let keyboardIdle = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .keyDown)
    let event: [String: Any] = ["ts": Date().timeIntervalSince1970, "mono": ProcessInfo.processInfo.systemUptime, "app": bundle, "app_name": app?.localizedName ?? "Unknown", "title": title, "document": document, "idle": idle, "mouse_idle": mouseIdle.isFinite ? mouseIdle : idle, "keyboard_idle": keyboardIdle.isFinite ? keyboardIdle : idle, "locked": locked, "accessibility": trusted, "desktop_context": contextText, "context_scope": contextScope]
    if let data = try? JSONSerialization.data(withJSONObject: event) {
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data([10]))
    }
}
emit()
if CommandLine.arguments.contains("--once") { exit(0) }
let timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { _ in emit() }
RunLoop.main.run()
