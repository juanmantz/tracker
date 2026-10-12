import AppKit
import WebKit

// The shipped executable owns the window. Python is private, bundled service code.
final class DreamsTimeApp: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    var window: NSWindow!
    var webView: WKWebView!
    var loading: NSTextField!
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
        showWindow()
        startService()
        if smokeTest {
            DispatchQueue.main.asyncAfter(deadline: .now() + 60) {
                fputs("Mac app smoke test timed out.\n", stderr)
                exit(1)
            }
        }
    }

    func startService() {
        DispatchQueue.global().async {
            let process = makeLauncher()
            do {
                try process.run()
                process.waitUntilExit()
                DispatchQueue.main.async {
                    if process.terminationStatus == 0 {
                        self.webView.load(URLRequest(url: self.origin))
                    } else {
                        self.startFailed()
                    }
                }
            } catch {
                DispatchQueue.main.async { self.startFailed() }
            }
        }
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

    @objc func showWindow() {
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow()
        // Opening the app also recovers a service that was stopped from the old UI.
        startService()
        return true
    }

    @objc func quitApp() {
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
    environment["DREAMSTIME_INSTALLED"] = "1"
    process.environment = environment
    return process
}

if CommandLine.arguments.contains("--background") {
    let process = makeLauncher()
    do { try process.run(); process.waitUntilExit(); exit(process.terminationStatus) }
    catch { exit(1) }
}
let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = DreamsTimeApp()
app.delegate = delegate
app.run()
