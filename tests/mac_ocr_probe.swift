// CI-only diagnostic for a known synthetic window. Never bundled in the app.
import AppKit
import ScreenCaptureKit

@available(macOS 14.0, *)
final class Probe: NSObject, NSApplicationDelegate {
    let reader=ScreenContext()
    let pid=Int32(CommandLine.arguments[1])!
    let output=URL(fileURLWithPath:CommandLine.arguments[2])
    let picture=URL(fileURLWithPath:CommandLine.arguments[3])
    var attempts=0
    var done=false
    func finish(_ value:[String:Any]) {
        try? JSONSerialization.data(withJSONObject:value).write(to:output)
        NSApp.terminate(nil)
    }
    func applicationDidFinishLaunching(_ notification:Notification) {
        _=Timer.scheduledTimer(withTimeInterval:1,repeats:true){_ in
            guard !self.done else { return }
            self.attempts += 1
            if let (text,_)=self.reader.evidence(pid:self.pid,bundle:"com.openai.chatgpt",active:true,enabled:true) {
                self.done=true
                SCShareableContent.getExcludingDesktopWindows(true,onScreenWindowsOnly:true){content,error in
                    guard let window=content?.windows.first(where:{$0.owningApplication?.processID==self.pid && $0.windowLayer==0}) else {
                        DispatchQueue.main.async {self.finish(["ocr":text,"frame":"unavailable"])};return
                    }
                    let config=SCStreamConfiguration()
                    config.width=Int(window.frame.width);config.height=Int(window.frame.height)
                    config.showsCursor=false;config.scalesToFit=true
                    SCScreenshotManager.captureImage(contentFilter:SCContentFilter(desktopIndependentWindow:window),configuration:config){image,error in
                        if let image=image {try? NSBitmapImageRep(cgImage:image).representation(using:.png,properties:[:])?.write(to:self.picture)}
                        DispatchQueue.main.async {self.finish(["ocr":text,"width":image?.width ?? 0,"height":image?.height ?? 0,"state":self.reader.state])}
                    }
                }
            } else if self.attempts>30 {self.done=true;self.finish(["state":self.reader.state,"captures":self.reader.captures])}
        }
    }
}

@main struct Main {
    static func main() {
        guard CommandLine.arguments.count==4 else {exit(1)}
        if #available(macOS 14.0, *) {
            let app=NSApplication.shared
            app.setActivationPolicy(.accessory)
            let probe=Probe();app.delegate=probe;app.run()
        }
    }
}
