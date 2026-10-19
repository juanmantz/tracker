// macOS context snapshots and connected-call sensor; visible conversation matching is local.
// Never captures screenshots, editable chat content, keystrokes or call audio.
import AppKit
import ApplicationServices
import Foundation

// Both the installed app and the development command share this implementation.
// Installed collection runs inside the app that macOS grants Accessibility to.
func startNativeActivitySensor(requestPermission: Bool = false,
                               contextEnabled: @escaping () -> Bool,
                               enabled: @escaping () -> Bool = { true },
                               receive: @escaping ([String: Any]) -> Void) -> Timer {
    let prompt = requestPermission
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

    let chatApps: Set<String> = ["com.openai.chat", "com.openai.chatgpt", "com.openai.codex"]
    let callApps: Set<String> = ["net.whatsapp.WhatsApp", "com.whatsapp.WhatsApp", "us.zoom.xos", "com.apple.FaceTime", "com.microsoft.teams", "com.microsoft.teams2", "com.tinyspeck.slackmacgap"]
    let editable: Set<String> = ["AXTextField", "AXTextArea", "AXSecureTextField", "AXComboBox", "AXOutline"]
    var callSessions: [String: String] = [:]
    var snapshotCache: (key: String, at: Double, card: [String: Any]?)?
    var preparedApplications = Set<pid_t>()

    func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
        AXUIElementSetMessagingTimeout(element, 0.025)
        var value: CFTypeRef?
        return AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success ? value : nil
    }
    func text(_ element: AXUIElement, _ name: String) -> String {
        return attribute(element, name) as? String ?? ""
    }
    func elementValue(_ value: CFTypeRef?) -> AXUIElement? {
        guard let value = value, CFGetTypeID(value) == AXUIElementGetTypeID() else { return nil }
        return unsafeBitCast(value, to: AXUIElement.self)
    }
    func children(_ element: AXUIElement) -> [AXUIElement] {
        return attribute(element, "AXChildren") as? [AXUIElement] ?? []
    }
    func headerSnapshot(_ root: AXUIElement, bundle: String, title: String) -> [String: Any]? {
        let deadline = Date().timeIntervalSince1970 + 0.12
        var queue: [(AXUIElement, Int, Bool, Bool)] = [(root, 0, false, false)]
        var visited = 0
        var labels: [String] = []
        var mainHeader = false
        let generic: Set<String> = ["chatgpt", "figma", "new chat", "new tab", "search", "share", "edit", "file", "view", "window", "help", "close", "minimize", "zoom", "untitled"]
        while !queue.isEmpty && visited < 100 && Date().timeIntervalSince1970 < deadline {
            let (node, depth, toolbar, main) = queue.removeFirst()
            visited += 1
            let role = text(node, "AXRole")
            if editable.contains(role) { continue }
            let description = text(node, "AXDescription").lowercased()
            let identifier = text(node, "AXIdentifier").lowercased()
            if ["sidebar", "navigation", "chat history"].contains(where: { description.contains($0) || identifier.contains($0) }) { continue }
            let inToolbar = toolbar || role == "AXToolbar"
            let inMain = main || text(node, "AXSubrole") == "AXLandmarkMain" ||
                ["conversation", "chat messages", "main content"].contains(description)
            let explicitHeader = ["document-title", "conversation-title", "meeting-title"].contains(identifier) ||
                ["document title", "conversation title", "meeting title"].contains(description)
            let isHeader = explicitHeader || (role == "AXStaticText" && inToolbar) ||
                (role == "AXHeading" && inMain && depth <= 6)
            if isHeader {
                let value = text(node, "AXValue")
                let label = String((value.isEmpty ? text(node, "AXTitle") : value)
                    .split(whereSeparator: { $0.isWhitespace }).joined(separator: " ").prefix(96))
                if !label.isEmpty && !generic.contains(label.lowercased()) && label != title &&
                    !labels.contains(where: { $0.caseInsensitiveCompare(label) == .orderedSame }) {
                    labels.append(label)
                    mainHeader = mainHeader || (chatApps.contains(bundle) && (inMain || explicitHeader))
                }
                if labels.count == 4 { break }
            }
            if depth < 8 { queue.append(contentsOf: children(node).prefix(30).map { ($0, depth + 1, inToolbar, inMain) }) }
        }
        if labels.isEmpty {
            let windowTitle = title.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
            let appTitle = NSWorkspace.shared.runningApplications.first(where: { $0.bundleIdentifier == bundle })?.localizedName ?? ""
            guard !windowTitle.isEmpty, !generic.contains(windowTitle.lowercased()),
                  windowTitle.caseInsensitiveCompare(appTitle) != .orderedSame else { return nil }
            return ["schema": "dreamstime/context/v1", "kind": "window", "scope": "window_metadata",
                    "labels": [String(windowTitle.prefix(96))]]
        }
        return ["schema": "dreamstime/context/v1", "kind": chatApps.contains(bundle) ? "conversation" : "document",
                "scope": mainHeader ? "conversation_header" : "document_header", "labels": labels]
    }
    func connectedControls(_ root: AXUIElement, deadline: Double) -> Bool {
        var queue: [(AXUIElement, Int)] = [(root, 0)]
        var visited = 0
        var hasEndControl = false
        var hasDuration = false
        var pending = false
        let duration = try! NSRegularExpression(pattern: "^(?:call duration |duration )?[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?$", options: [.caseInsensitive])
        while !queue.isEmpty && visited < 120 && Date().timeIntervalSince1970 < deadline {
            let (node, depth) = queue.removeFirst()
            visited += 1
            let role = text(node, "AXRole")
            if editable.contains(role) { continue }
            if role == "AXButton" || role == "AXMenuButton" {
                let label = (text(node, "AXTitle") + " " + text(node, "AXDescription") + " " + text(node, "AXHelp")).lowercased()
                if attribute(node, "AXEnabled") as? Bool == true && ["end call", "end video call", "hang up", "leave meeting", "leave call", "leave huddle", "finalizar llamada", "colgar"].contains(where: { label.contains($0) }) {
                    hasEndControl = true
                }
            } else if role == "AXStaticText" || role == "AXHeading" {
                let value = text(node, "AXValue")
                let label = (value.isEmpty ? text(node, "AXTitle") : value).trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
                if ["calling", "ringing", "connecting", "call ended", "llamando", "conectando", "llamada finalizada"].contains(label.trimmingCharacters(in: CharacterSet(charactersIn: ".… "))) {
                    pending = true
                }
                if duration.firstMatch(in: label, range: NSRange(label.startIndex..., in: label)) != nil &&
                    label.contains(where: { $0 >= "1" && $0 <= "9" }) { hasDuration = true }
            }
            if depth < 9 { queue.append(contentsOf: children(node).prefix(35).map { ($0, depth + 1) }) }
        }
        return hasEndControl && hasDuration && !pending
    }
    func connectedCall(front: String) -> (app: String, name: String, title: String, session: String, snapshot: [String: Any])? {
        let deadline = Date().timeIntervalSince1970 + 0.20
        var found: [(app: String, name: String, title: String, session: String, snapshot: [String: Any])] = []
        var activeKeys = Set<String>()
        let apps = NSWorkspace.shared.runningApplications.filter { callApps.contains($0.bundleIdentifier ?? "") }
            .sorted { ($0.bundleIdentifier == front ? 0 : 1) < ($1.bundleIdentifier == front ? 0 : 1) }
        for app in apps {
            if Date().timeIntervalSince1970 >= deadline { break }
            let element = AXUIElementCreateApplication(app.processIdentifier)
            let windows = attribute(element, "AXWindows") as? [AXUIElement] ?? []
            for window in windows.prefix(4) {
                if Date().timeIntervalSince1970 >= deadline { break }
                guard connectedControls(window, deadline: deadline) else { continue }
                let title = String(text(window, "AXTitle").prefix(160))
                let bundle = app.bundleIdentifier ?? ""
                let key = bundle + ":" + String(app.processIdentifier) + ":" + String(CFHash(window))
                activeKeys.insert(key)
                let session = callSessions[key] ?? UUID().uuidString.lowercased()
                callSessions[key] = session
                // A call title/participant label is metadata; no call audio or chat body is read.
                let labels = title.isEmpty || title == app.localizedName ? [] : [title]
                found.append((bundle, app.localizedName ?? bundle, title, session,
                    ["schema": "dreamstime/context/v1", "kind": "call", "scope": "call_controls",
                     "labels": labels, "state": "connected"]))
            }
        }
        callSessions = callSessions.filter { activeKeys.contains($0.key) }
        if found.count == 1 { return found[0] }
        let foreground = found.filter { $0.app == front }
        return foreground.count == 1 ? foreground[0] : nil
    }

    var lastConversationAt = 0.0
    // Only promote text from an explicitly identified conversation/main region.
    // A whole-window scan may contain unrelated chats in the sidebar.
    func conversationPane(_ root: AXUIElement, focused: AXUIElement?) -> AXUIElement? {
        func isNavigation(_ node: AXUIElement) -> Bool {
            let description = text(node, "AXDescription").lowercased()
            let identifier = text(node, "AXIdentifier").lowercased()
            let subrole = text(node, "AXSubrole")
            return ["AXLandmarkNavigation", "AXLandmarkComplementary"].contains(subrole) ||
                ["sidebar", "navigation", "chat history"].contains(where: { description.contains($0) || identifier.contains($0) })
        }
        func isConversation(_ node: AXUIElement) -> Bool {
            if isNavigation(node) { return false }
            return text(node, "AXSubrole") == "AXLandmarkMain" || text(node, "AXRole") == "AXLandmarkMain" ||
                ["conversation", "chat messages", "main content"].contains(text(node, "AXDescription").lowercased()) ||
                ["conversation", "main-content", "conversation-pane"].contains(text(node, "AXIdentifier").lowercased())
        }
        // The focused composer is often deeply nested. Walk only its parents
        // to find an explicitly marked main region; never infer a whole window.
        var ancestor = focused
        var parents = Set<CFHashCode>()
        for _ in 0..<24 {
            guard let node = ancestor, parents.insert(CFHash(node)).inserted else { break }
            if isNavigation(node) { break }
            if isConversation(node) { return node }
            ancestor = elementValue(attribute(node, "AXParent"))
        }
        var queue: [AXUIElement] = [root]
        let deadline = Date().timeIntervalSince1970 + 0.3
        var visited = 0
        while !queue.isEmpty && visited < 240 && Date().timeIntervalSince1970 < deadline {
            let node = queue.removeFirst()
            visited += 1
            AXUIElementSetMessagingTimeout(node, 0.04)
            var roleValue: CFTypeRef?
            _ = AXUIElementCopyAttributeValue(node, kAXRoleAttribute as CFString, &roleValue)
            let role = roleValue as? String ?? ""
            if ["AXTextField", "AXTextArea", "AXSecureTextField", "AXComboBox", "AXOutline", "AXToolbar"].contains(role) { continue }
            if isNavigation(node) { continue }
            if isConversation(node) { return node }
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
            let subrole = text(node, "AXSubrole")
            let description = text(node, "AXDescription").lowercased()
            let identifier = text(node, "AXIdentifier").lowercased()
            if ["AXLandmarkNavigation", "AXLandmarkComplementary"].contains(subrole) ||
                ["sidebar", "navigation", "chat history"].contains(where: { description.contains($0) || identifier.contains($0) }) { continue }
            if role == "AXStaticText" || role == "AXHeading" {
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
        if !enabled() { receive(["heartbeat": true]); return }
        let foreground = NSWorkspace.shared.frontmostApplication
        let frontBundle = foreground?.bundleIdentifier ?? ""
        let trusted = AXIsProcessTrusted()
        let session = CGSessionCopyCurrentDictionary() as? [String: Any]
        let locked = session == nil || !sessionActive || !awake ||
            (session?["CGSSessionScreenIsLocked"] as? Bool ?? false) ||
            (session?["kCGSSessionOnConsoleKey"] as? Bool == false) || frontBundle == "com.apple.loginwindow"
        let idle = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: CGEventType(rawValue: UInt32.max)!)
        guard idle.isFinite && idle >= 0 else { fputs("macOS returned an invalid idle duration.\n", stderr); exit(1) }
        let browsers: Set<String> = ["com.google.Chrome", "com.google.Chrome.beta", "com.microsoft.edgemac", "com.brave.Browser", "company.thebrowser.Browser", "com.apple.Safari", "org.mozilla.firefox"]
        let excluded: Set<String> = ["com.agilebits.onepassword7", "com.1password.1password", "com.apple.loginwindow"]
        var bundle = frontBundle
        var appName = foreground?.localizedName ?? "Unknown"
        var title = ""
        var document = ""
        var windowAccessStatus = "not_requested"
        var focusedWindow: AXUIElement?
        var focusedElement: AXUIElement?
        if !locked, let pid = foreground?.processIdentifier, !browsers.contains(bundle), !excluded.contains(bundle) {
            let element = AXUIElementCreateApplication(pid)
            if trusted && contextEnabled() && (chatApps.contains(bundle) ||
                ["com.figma.Desktop", "com.tinyspeck.slackmacgap"].contains(bundle)) && preparedApplications.insert(pid).inserted {
                // Electron applications may not build their Accessibility tree
                // until an assistive client asks. This never grants OS access.
                _ = AXUIElementSetAttributeValue(element, "AXManualAccessibility" as CFString, kCFBooleanTrue)
                _ = AXUIElementSetAttributeValue(element, "AXEnhancedUserInterface" as CFString, kCFBooleanTrue)
            }
            AXUIElementSetMessagingTimeout(element, 0.2)
            var value: CFTypeRef?
            let result = AXUIElementCopyAttributeValue(element, kAXFocusedWindowAttribute as CFString, &value)
            windowAccessStatus = result == .success ? "readable" : "ax_error_\(result.rawValue)"
            if result == .success, let value = value, CFGetTypeID(value) == AXUIElementGetTypeID() {
                let window = unsafeBitCast(value, to: AXUIElement.self)
                focusedWindow = window
                title = text(window, "AXTitle")
                let location = attribute(window, "AXDocument")
                document = location as? String ?? (location as? URL)?.absoluteString ?? ""
                if chatApps.contains(bundle) {
                    focusedElement = elementValue(attribute(element, "AXFocusedUIElement"))
                }
            }
        }
        var snapshot: [String: Any]?
        var callID: String?
        if !locked && !excluded.contains(frontBundle) && contextEnabled() {
            if trusted, let call = connectedCall(front: frontBundle) {
                bundle = call.app
                appName = call.name
                title = call.title
                document = ""
                callID = call.session
                snapshot = call.snapshot
                windowAccessStatus = "readable"
            } else if let window = focusedWindow {
                let key = bundle + "\n" + title + "\n" + document
                let now = Date().timeIntervalSince1970
                let interval = idle >= 120 ? 60.0 : (chatApps.contains(bundle) && document.isEmpty ? 2.0 : 15.0)
                if let cache = snapshotCache, cache.key == key, now - cache.at < interval {
                    snapshot = cache.card
                } else {
                    snapshot = headerSnapshot(window, bundle: bundle, title: title)
                    snapshotCache = (key, now, snapshot)
                }
            }
        } else {
            snapshotCache = nil
            callSessions.removeAll()
        }
        let mouseTypes: [CGEventType] = [.mouseMoved, .leftMouseDragged, .rightMouseDragged, .otherMouseDragged, .leftMouseDown, .rightMouseDown, .otherMouseDown, .scrollWheel]
        let mouseIdle = mouseTypes.map { CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: $0) }.min() ?? idle
        let keyboardIdle = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .keyDown)
        let now = Date().timeIntervalSince1970
        var conversationText = ""
        if !locked && idle < 120 && callID == nil && contextEnabled() &&
            chatApps.contains(bundle) && now - lastConversationAt >= 10,
            let window = focusedWindow, let pane = conversationPane(window, focused: focusedElement) {
            // Compare only the current conversation locally. The backend retains
            // project-ID hints; it never stores or uploads this text.
            conversationText = visibleText(pane)
            lastConversationAt = now
        }
        var captureState = "no_specific_context"
        if !contextEnabled() { captureState = "disabled" }
        else if locked { captureState = "locked" }
        else if !trusted { captureState = "permission_required" }
        else if browsers.contains(frontBundle) { captureState = "browser_companion_required" }
        else if !conversationText.isEmpty { captureState = "current_conversation" }
        else if snapshot != nil { captureState = snapshot?["scope"] as? String == "window_metadata" ? "window_metadata" : "compact_header" }
        else if chatApps.contains(bundle) { captureState = "conversation_region_unavailable" }
        var event: [String: Any] = ["ts": now, "mono": ProcessInfo.processInfo.systemUptime,
            "app": bundle, "app_name": appName, "title": title, "document": document,
            "idle": idle, "mouse_idle": mouseIdle.isFinite ? mouseIdle : idle,
            "keyboard_idle": keyboardIdle.isFinite ? keyboardIdle : idle, "locked": locked,
            "accessibility": trusted || (windowAccessStatus == "readable" && foreground?.processIdentifier != ProcessInfo.processInfo.processIdentifier), "ax_trusted": trusted,
            "window_access_status": windowAccessStatus, "collector_bundle": Bundle.main.bundleIdentifier ?? "standalone",
            "collector_pid": ProcessInfo.processInfo.processIdentifier,
            "context_enabled": contextEnabled(), "context_capture_state": captureState]
        if !conversationText.isEmpty {
            event["desktop_context"] = conversationText
            event["context_scope"] = "conversation"
        }
        if let snapshot = snapshot { event["context_snapshot"] = snapshot }
        if let callID = callID {
            event["call_active"] = true
            event["call_session"] = callID
            event["call_verified_at"] = now
            event["call_proof"] = "end-control+duration"
        }
        receive(event)
    }

    emit()
    return Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { _ in
        _ = observers // Keep workspace notification tokens alive with the timer.
        emit()
    }
}

#if !DREAMSTIME_APP
@main
struct StandaloneActivitySensor {
    static func main() {
        let timer = startNativeActivitySensor(
            requestPermission: CommandLine.arguments.contains("--request-permission"),
            contextEnabled: { CommandLine.arguments.contains("--chatgpt-context") }
        ) { event in
            if let data = try? JSONSerialization.data(withJSONObject: event) {
                FileHandle.standardOutput.write(data)
                FileHandle.standardOutput.write(Data([10]))
            }
        }
        _ = timer
        if CommandLine.arguments.contains("--once") { exit(0) }
        RunLoop.main.run()
    }
}
#endif
