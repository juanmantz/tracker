import AppKit
import WebKit
import ApplicationServices
import Darwin

// The shipped executable owns the window. Python is private, bundled service code.
final class DreamsTimeApp: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    var window: NSWindow!
    var webView: WKWebView!
    var loading: NSTextField!
    var background = CommandLine.arguments.contains("--background")
    var permissionPrompted = false
    var screenPrompted = false
    var screenRepairInProgress = false
    var screenSettingsSeen = false
    var screenRequestAt: Double = 0
    var permissionRepairInProgress = false
    var permissionSettingsSeen = false
    var permissionRepairStarted: Double = 0
    var collectorRestarting = false
    var nativeTimer: Timer?
    var serviceStarting = false
    var samplePending = false
    var nativePaused = false
    var desktopContextEnabled = false
    var consecutiveFailures = 0
    var smokeTest = CommandLine.arguments.contains("--smoke-test")
    var home = FileManager.default.homeDirectoryForCurrentUser
    var origin = URL(string: "http://127.0.0.1:43123")!

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Open Dreams Time", action: #selector(showWindow), keyEquivalent: "0").target = self
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit Dreams Time", action: #selector(quitApp), keyEquivalent: "q").target = self
        appItem.submenu = appMenu
        menu.addItem(appItem)
        let editItem = NSMenuItem(title: "Edit", action: nil, keyEquivalent: "")
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = editMenu
        menu.addItem(editItem)
        NSApp.mainMenu = menu

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 920, height: 790), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Dreams Time"
        window.minSize = NSSize(width: 580, height: 540)
        window.isReleasedWhenClosed = false
        window.center()
        let config = WKWebViewConfiguration()
        config.userContentController.add(self, name: "dreamsTime")
        webView = WKWebView(frame: window.contentView!.bounds, configuration: config)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        window.contentView!.addSubview(webView)
        loading = NSTextField(labelWithString: "Starting Dreams Time…")
        loading.frame = NSRect(x: 30, y: 355, width: 860, height: 40)
        loading.alignment = .center
        loading.font = .systemFont(ofSize: 20)
        loading.autoresizingMask = [.width, .minYMargin, .maxYMargin]
        window.contentView!.addSubview(loading)
        DistributedNotificationCenter.default().addObserver(self,
            selector: #selector(reopenRequested(_:)), name: Notification.Name("local.dreamstime.reopen"),
            object: nil, suspensionBehavior: .deliverImmediately)
        if !background { showWindow() }
        startService()
        if smokeTest {
            DispatchQueue.main.asyncAfter(deadline: .now() + 60) {
                fputs("Mac app smoke test timed out.\n", stderr)
                exit(1)
            }
        }
    }

    func startService() {
        guard !serviceStarting else { return }
        serviceStarting = true
        DispatchQueue.global().async {
            let process = makeLauncher()
            do {
                try process.run()
                process.waitUntilExit()
                DispatchQueue.main.async {
                    self.serviceStarting = false
                    if process.terminationStatus == 0 {
                        self.startCollection()
                        self.webView.load(URLRequest(url: self.origin))
                    } else {
                        self.startFailed()
                    }
                }
            } catch {
                DispatchQueue.main.async { self.serviceStarting = false; self.startFailed() }
            }
        }
    }


    func startCollection() {
        guard nativeTimer == nil, !smokeTest else { return }
        // The sampler lives in this exact process and bundle, never Python or
        // a differently signed helper. This is the identity shown in Settings.
        nativeTimer = startNativeActivitySensor(
            requestPermission: false,
            contextEnabled: { self.desktopContextEnabled },
            enabled: { !self.nativePaused }
        ) { sample in self.submitSample(sample) }
    }

    func submitSample(_ rawSample: [String: Any]) {
        checkPermissionRepair()
        checkScreenPermission()
        var sample = rawSample
        sample["screen_permission_setup"] = screenRepairInProgress ? (screenSettingsSeen ? "settings_open" : "waiting_for_allow") : (CGPreflightScreenCaptureAccess() ? "ready" : "required")
        sample["permission_repair"] = permissionRepairInProgress ? (permissionSettingsSeen ? "settings_open" : "waiting_for_allow") : (AXIsProcessTrusted() ? "ready" : "required")
        let support = home.appendingPathComponent("Library/Application Support/Dreams Time")
        if FileManager.default.fileExists(atPath: support.appendingPathComponent(".stopped").path) {
            NSApp.terminate(nil)
            return
        }
        guard !samplePending, let token = try? String(
            contentsOf: support.appendingPathComponent("pairing-token"), encoding: .utf8
        ).trimmingCharacters(in: .whitespacesAndNewlines) else { return }
        var request = URLRequest(url: origin.appendingPathComponent("api/native/sample"))
        request.httpMethod = "POST"
        request.timeoutInterval = 3
        request.httpBody = try? JSONSerialization.data(withJSONObject: sample)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        samplePending = true
        URLSession.shared.dataTask(with: request) { data, response, error in
            DispatchQueue.main.async {
                self.samplePending = false
                if error == nil, (response as? HTTPURLResponse)?.statusCode == 200,
                   let data = data,
                   let settings = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] {
                    self.consecutiveFailures = 0
                    self.nativePaused = settings["paused"] as? Bool ?? true
                    self.desktopContextEnabled = settings["desktop_context_enabled"] as? Bool ?? false
                    if !self.background && self.desktopContextEnabled && !self.screenPrompted && !CGPreflightScreenCaptureAccess() {
                        self.screenPrompted = true
                        // A visible setup action is available if the owner has
                        // dismissed the system prompt. Background starts stay quiet.
                        if !UserDefaults.standard.bool(forKey: "screenCaptureRequested") { self.requestScreenAccess() }
                    }
                } else {
                    self.consecutiveFailures += 1
                    if self.consecutiveFailures >= 2 { self.startService() }
                }
            }
        }.resume()
    }

    func startFailed() {
        if smokeTest { fputs("The bundled service could not start.\n", stderr); exit(1) }
        loading.stringValue = "Dreams Time could not start."
        let alert = NSAlert()
        alert.messageText = "Dreams Time could not start"
        alert.informativeText = "Your recorded hours are kept. Retry to start the app."
        alert.addButton(withTitle: "Retry")
        alert.addButton(withTitle: "Close")
        if alert.runModal() == .alertFirstButtonReturn { startService() }
    }

    @objc func reopenRequested(_ notification: Notification) {
        showWindow()
        if notification.object as? String == "repair-access" { repairAccess() }
        if notification.object as? String == "screen-access" { requestScreenAccess() }
        startService()
    }

    @objc func showWindow() {
        background = false
        NSApp.setActivationPolicy(.regular)
        // Do not reset Accessibility on every app update. Screen OCR can work
        // independently; an explicit repair action remains in Settings.
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func repairAccess(automatic: Bool = false) {
        guard !smokeTest, !AXIsProcessTrusted(), !permissionRepairInProgress else { return }
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "unknown"
        let defaults = UserDefaults.standard
        // One foreground repair per installed build. Background launches never
        // reset a grant or open Settings, and valid access is never reset.
        if automatic && defaults.string(forKey: "permissionRepairVersion") == version { return }
        defaults.set(version, forKey: "permissionRepairVersion")
        permissionRepairInProgress = true
        permissionSettingsSeen = false
        permissionRepairStarted = Date().timeIntervalSince1970
        let reset = Process()
        reset.executableURL = URL(fileURLWithPath: "/usr/bin/tccutil")
        // Public macOS utility, scoped exclusively to this app. No TCC database
        // edits, all-app resets, Keychain reads, or automatic permission grants.
        reset.arguments = ["reset", "Accessibility", "local.dreamstime.companion"]
        reset.standardOutput = FileHandle.nullDevice
        reset.standardError = FileHandle.nullDevice
        reset.terminationHandler = { _ in
            DispatchQueue.main.async { self.requestCurrentAppAccess() }
        }
        do { try reset.run() } catch { requestCurrentAppAccess() }
    }

    func requestCurrentAppAccess() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(options)
        if let settings = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
            NSWorkspace.shared.open(settings)
        }
    }

    func requestScreenAccess() {
        guard !smokeTest else { return }
        screenRepairInProgress = true
        screenSettingsSeen = false
        screenRequestAt = Date().timeIntervalSince1970
        UserDefaults.standard.set(true, forKey: "screenCaptureRequested")
        DispatchQueue.global().async {
            let granted = CGRequestScreenCaptureAccess()
            DispatchQueue.main.async {
                if !granted, let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture") {
                    NSWorkspace.shared.open(url)
                }
            }
        }
    }

    func checkScreenPermission() {
        guard screenRepairInProgress else { return }
        let front = NSWorkspace.shared.frontmostApplication?.bundleIdentifier ?? ""
        if front == "com.apple.systempreferences" { screenSettingsSeen = true }
        if CGPreflightScreenCaptureAccess() || (screenSettingsSeen && front != "com.apple.systempreferences") {
            screenRepairInProgress = false
            // macOS can cache a Screen Recording denial until process restart.
            // Refresh once after setup; the service and measured history survive.
            restartCollector()
        } else if Date().timeIntervalSince1970 - screenRequestAt > 600 {
            screenRepairInProgress = false
        }
    }

    func checkPermissionRepair() {
        guard permissionRepairInProgress else { return }
        let front = NSWorkspace.shared.frontmostApplication?.bundleIdentifier ?? ""
        if front == "com.apple.systempreferences" { permissionSettingsSeen = true }
        let granted = AXIsProcessTrusted()
        // Refresh the actual native process once when access is granted or the
        // user leaves Settings. This also clears a cached denial. Never loop.
        if granted || (permissionSettingsSeen && front != "com.apple.systempreferences") {
            permissionRepairInProgress = false
            restartCollector()
        } else if Date().timeIntervalSince1970 - permissionRepairStarted > 600 {
            permissionRepairInProgress = false
        }
    }

    func restartCollector() {
        guard !smokeTest, !collectorRestarting else { return }
        collectorRestarting = true
        let restart = Process()
        restart.executableURL = URL(fileURLWithPath: "/bin/sh")
        // Pass the path as an argument, never interpolate a shell command.
        restart.arguments = ["-c", "sleep 1; exec /usr/bin/open -n \"$1\"", "dreamstime-reopen", Bundle.main.bundleURL.path]
        do {
            try restart.run()
            // No .stopped flag: the measured-time service and sign-in survive.
            NSApp.terminate(nil)
        } catch { collectorRestarting = false }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow()
        // Opening the app also recovers a service that was stopped from the old UI.
        startService()
        return true
    }

    @objc func quitApp() {
        let stopURL = home.appendingPathComponent("Library/Application Support/Dreams Time/.stopped")
        FileManager.default.createFile(atPath: stopURL.path, contents: Data())
        let tokenURL = home.appendingPathComponent("Library/Application Support/Dreams Time/pairing-token")
        guard let token = try? String(contentsOf: tokenURL, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines) else {
            NSApp.terminate(nil); return
        }
        var request = URLRequest(url: origin.appendingPathComponent("api/quit"))
        request.httpMethod = "POST"
        request.timeoutInterval = 2
        request.httpBody = Data("{}".utf8)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        URLSession.shared.dataTask(with: request) { _,_,_ in DispatchQueue.main.async { NSApp.terminate(nil) } }.resume()
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if url.host == "127.0.0.1" && url.port == 43123 {
            decisionHandler(.allow)
        } else {
            if url.scheme == "https" { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel)
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        loading.isHidden = true
        if smokeTest {
            webView.evaluateJavaScript("document.title + '|' + !!window.webkit.messageHandlers.dreamsTime") { value,error in
                guard error == nil, let value = value as? String, value == "Dreams Time|true" else {
                    fputs("Native app failed to render the local interface.\n", stderr); exit(1)
                }
                print("Mac app rendered the bundled interface in its native window.")
                fflush(stdout)
                NSApp.terminate(nil)
            }
        }
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, let url = message.frameInfo.request.url,
              url.host == "127.0.0.1", url.port == 43123,
              let body = message.body as? [String: String] else { return }
        switch body["type"] {
        case "repair-access":
            if AXIsProcessTrusted() { requestCurrentAppAccess() } else { repairAccess() }
        case "restart-collector": restartCollector()
        case "screen-access": requestScreenAccess()
        case "open-url":
            if let raw = body["url"], let url = URL(string: raw), url.scheme == "https", url.host == "dreams.checklists.workers.dev" { NSWorkspace.shared.open(url) }
        case "copy":
            if let value = body["text"] { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(value, forType: .string) }
        case "download":
            guard let name = body["name"], let content = body["content"] else { return }
            let panel = NSSavePanel()
            panel.nameFieldStringValue = URL(fileURLWithPath: name).lastPathComponent
            panel.beginSheetModal(for: window) { result in
                if result == .OK, let url = panel.url { try? Data(content.utf8).write(to: url, options: .atomic) }
            }
        case "quit": NSApp.terminate(nil)
        default: break
        }
    }
}

func makeLauncher() -> Process {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/bin/bash")
    process.arguments = [Bundle.main.resourceURL!.appendingPathComponent("launch-mac.sh").path]
    var environment = ProcessInfo.processInfo.environment
    environment["DREAMSTIME_APP_BUNDLE"] = Bundle.main.bundleURL.path
    environment["DREAMSTIME_HEADLESS"] = "1"
    environment["DREAMSTIME_NATIVE_HOST"] = "1"
    environment["DREAMSTIME_INSTALLED"] = "1"
    environment["DREAMSTIME_BACKGROUND"] = CommandLine.arguments.contains("--background") ? "1" : "0"
    process.environment = environment
    return process
}

@main
struct DreamsTimeMain {
    private static var instanceLock: Int32 = -1

    static func claimInstance() -> Bool {
        let support = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Dreams Time")
        do {
            try FileManager.default.createDirectory(at: support, withIntermediateDirectories: true,
                                                   attributes: [.posixPermissions: 0o700])
        } catch { return false }
        let path = support.appendingPathComponent(".native-instance.lock").path
        let descriptor = Darwin.open(path, O_CREAT | O_RDWR, mode_t(0o600))
        guard descriptor >= 0 else { return false }
        var recordLock = Darwin.flock()
        recordLock.l_type = Int16(F_WRLCK)
        recordLock.l_whence = Int16(SEEK_SET)
        recordLock.l_start = 0
        recordLock.l_len = 0
        guard Darwin.fcntl(descriptor, F_SETLK, &recordLock) == 0 else {
            Darwin.close(descriptor)
            if !CommandLine.arguments.contains("--background") {
                DistributedNotificationCenter.default().postNotificationName(
                    Notification.Name("local.dreamstime.reopen"), object: CommandLine.arguments.contains("--screen-access") ? "screen-access" : (CommandLine.arguments.contains("--repair-access") ? "repair-access" : nil), userInfo: nil,
                    deliverImmediately: true)
            }
            return false
        }
        _ = Darwin.fcntl(descriptor, F_SETFD, FD_CLOEXEC)
        instanceLock = descriptor // The OS releases this lock even after a crash.
        return true
    }

    static func main() {
        if CommandLine.arguments.contains("--background") {
            let support = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Dreams Time/.stopped")
            if FileManager.default.fileExists(atPath: support.path) { exit(0) }
        }
        if !CommandLine.arguments.contains("--smoke-test") && !claimInstance() { exit(0) }
        let app = NSApplication.shared
        app.setActivationPolicy(CommandLine.arguments.contains("--background") ? .accessory : .regular)
        let delegate = DreamsTimeApp()
        app.delegate = delegate
        app.run()
    }
}
