import AppKit
import ScreenCaptureKit
import Vision

// Pixels and OCR text live only in memory. The service retains project IDs and
// compact project-name evidence, never screenshots or a conversation transcript.
final class ScreenContext {
    private var pending = false
    private var lastAttempt: Double = 0
    private var cached: (pid: pid_t, window: CGWindowID, at: Double, text: String)?
    private(set) var state = "waiting"
    private(set) var captures = 0
    private(set) var failures = 0
    private var generation = 0
    static let chatApps: Set<String> = ["com.openai.chat", "com.openai.chatgpt", "com.openai.codex"]
    static let workApps: Set<String> = chatApps.union([
        "com.figma.Desktop", "com.tinyspeck.slackmacgap", "com.microsoft.VSCode",
        "com.todesktop.230313mzl4w4u92", "com.apple.iWork.Keynote", "com.apple.iWork.Pages",
        "com.adobe.Photoshop", "com.adobe.Illustrator", "com.adobe.AfterEffects",
        "net.whatsapp.WhatsApp", "com.whatsapp.WhatsApp", "us.zoom.xos",
        "com.microsoft.teams2", "com.microsoft.teams", "com.riversidefm.Riverside"
    ])

    func invalidate(_ reason: String) {
        generation += 1
        cached = nil
        state = reason
    }

    func evidence(pid: pid_t, bundle: String, active: Bool, enabled: Bool) -> (String, Double)? {
        guard enabled && active && Self.workApps.contains(bundle) else {
            invalidate(!enabled ? "disabled" : (!active ? "inactive" : "excluded_app"))
            return nil
        }
        guard #available(macOS 14.0, *) else { invalidate("requires_macos14"); return nil }
        guard CGPreflightScreenCaptureAccess() else { invalidate("permission_required"); return nil }
        // WindowServer ordering identifies the actual foreground window even
        // when the app's Accessibility tree is unavailable.
        let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
        guard let window = windows.first(where: {
            ($0[kCGWindowOwnerPID as String] as? Int) == Int(pid) &&
            ($0[kCGWindowLayer as String] as? Int) == 0 &&
            ($0[kCGWindowAlpha as String] as? Double ?? 0) > 0
        }), let number = window[kCGWindowNumber as String] as? UInt32 else { invalidate("window_unavailable"); return nil }
        let now = Date().timeIntervalSince1970
        if let old = cached, old.pid != pid || old.window != number { invalidate("waiting") }
        let result = cached.flatMap { $0.pid == pid && $0.window == number && now - $0.at <= 12 ? ($0.text, $0.at) : nil }
        if !pending && now - lastAttempt >= 10 {
            pending = true
            lastAttempt = now
            let ticket = generation
            state = "capturing"
            SCShareableContent.getExcludingDesktopWindows(true, onScreenWindowsOnly: true) { content, error in
                guard error == nil, let selected = content?.windows.first(where: { $0.windowID == number }) else {
                    DispatchQueue.main.async { self.pending = false; self.failures += 1; if ticket == self.generation { self.state = "capture_failed" } }
                    return
                }
                let filter = SCContentFilter(desktopIndependentWindow: selected)
                let config = SCStreamConfiguration()
                let scale = min(1.0, 1600.0 / max(1.0, max(selected.frame.width, selected.frame.height)))
                config.width = max(1, Int(selected.frame.width * scale))
                config.height = max(1, Int(selected.frame.height * scale))
                config.showsCursor = false
                config.scalesToFit = true
                SCScreenshotManager.captureImage(contentFilter: filter, configuration: config) { image, error in
                    DispatchQueue.global(qos: .utility).async {
                        var text = ""
                        if error == nil, let image = image {
                            let request = VNRecognizeTextRequest()
                            request.recognitionLevel = .accurate
                            request.usesLanguageCorrection = false
                            // Exclude ChatGPT history on the left and the bottom
                            // composer before OCR. No browser/incognito capture.
                            request.regionOfInterest = Self.chatApps.contains(bundle)
                                ? CGRect(x: 0.30, y: 0.30, width: 0.68, height: 0.65)
                                : CGRect(x: 0, y: 0.15, width: 1, height: 0.80)
                            if (try? VNImageRequestHandler(cgImage: image).perform([request])) != nil {
                                text = String((request.results ?? []).compactMap { observation -> String? in
                                    guard let value = observation.topCandidates(1).first, value.confidence >= 0.6 else { return nil }
                                    return value.string
                                }.joined(separator: "\n").prefix(6000))
                            }
                        }
                        DispatchQueue.main.async {
                            self.pending = false
                            guard ticket == self.generation, NSWorkspace.shared.frontmostApplication?.processIdentifier == pid else { return }
                            guard error == nil else { self.failures += 1; self.state = "capture_failed"; self.cached = nil; return }
                            self.captures += 1
                            self.state = text.isEmpty ? "no_readable_text" : "readable"
                            self.cached = (pid, number, Date().timeIntervalSince1970, text)
                        }
                    }
                }
            }
        }
        return result
    }
}
