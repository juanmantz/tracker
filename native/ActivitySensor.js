// macOS JXA sensor: /usr/bin/osascript runs this without developer tools.
// No keystrokes or screenshots. Browser titles remain delegated to the companion.
ObjC.import('AppKit');
ObjC.import('ApplicationServices');
ObjC.import('Foundation');

function readAttribute(element, name) {
  var output = Ref();
  var result = $.AXUIElementCopyAttributeValue(element, $(name), output);
  return result === 0 ? output[0] : null;
}
function stringValue(value) {
  if (!value) return '';
  if (typeof value === 'string') return value;
  try { var text = ObjC.unwrap(value); return typeof text === 'string' ? text : ''; }
  catch (_) { return ''; }
}
function visibleText(root) {
  var queue = [{element: root, depth: 0}], values = [], count = 0, deadline = Date.now() + 300;
  while (queue.length && count++ < 160 && Date.now() < deadline) {
    var item = queue.shift();
    $.AXUIElementSetMessagingTimeout(item.element, 0.08);
    var role = stringValue(readAttribute(item.element, 'AXRole'));
    if (['AXTextField', 'AXTextArea', 'AXSecureTextField', 'AXComboBox'].indexOf(role) >= 0) continue;
    if (role === 'AXStaticText') {
      var text = stringValue(readAttribute(item.element, 'AXValue'));
      if (text) values.push(text.slice(0, 1000));
    }
    if (item.depth < 8) {
      var children = readAttribute(item.element, 'AXChildren');
      if (children) {
        // Preserve AXUIElement references rather than deeply unwrapping them.
        var length = Number(children.count);
        for (var i = 0; i < Math.min(40, length); i++) queue.push({element: children.objectAtIndex(i), depth: item.depth + 1});
      }
    }
  }
  return values.join('\n').slice(0, 8000);
}
function run(argv) {
  var requestPermission = argv.indexOf('--request-permission') >= 0;
  var contextEnabled = argv.indexOf('--chatgpt-context') >= 0;
  var once = argv.indexOf('--once') >= 0;
  if (requestPermission) $.AXIsProcessTrustedWithOptions($({AXTrustedCheckOptionPrompt: true}));
  var lastContext = 0;
  var browsers = ['com.google.Chrome', 'com.google.Chrome.beta', 'com.microsoft.edgemac', 'com.brave.Browser', 'company.thebrowser.Browser', 'com.apple.Safari', 'org.mozilla.firefox'];
  var excluded = ['com.agilebits.onepassword7', 'com.1password.1password', 'com.apple.loginwindow'];
  var chatApps = ['com.openai.chat', 'com.openai.chatgpt', 'com.openai.codex'];
  do {
    var app = $.NSWorkspace.sharedWorkspace.frontmostApplication;
    var bundle = app ? stringValue(app.bundleIdentifier) : '';
    var appName = app ? stringValue(app.localizedName) : 'Unknown';
    var trusted = Boolean($.AXIsProcessTrusted());
    var title = '', context = '', document = '';
    if (app && trusted && browsers.indexOf(bundle) < 0 && excluded.indexOf(bundle) < 0) {
      var element = $.AXUIElementCreateApplication(app.processIdentifier);
      $.AXUIElementSetMessagingTimeout(element, 0.15);
      var window = readAttribute(element, 'AXFocusedWindow');
      if (window) {
        title = stringValue(readAttribute(window, 'AXTitle'));
        document = stringValue(readAttribute(window, 'AXDocument'));
        if (contextEnabled && chatApps.indexOf(bundle) >= 0 && Date.now() - lastContext > 10000) {
          context = visibleText(window);
          lastContext = Date.now();
        }
      }
    }
    var session = $.CGSessionCopyCurrentDictionary();
    var locked = true;
    if (session) {
      var state = ObjC.deepUnwrap(session);
      locked = Boolean(state.CGSSessionScreenIsLocked) || state.kCGSSessionOnConsoleKey === false || bundle === 'com.apple.loginwindow';
    }
    var idle = Number($.CGEventSourceSecondsSinceLastEventType(0, 4294967295));
    if (!isFinite(idle) || idle < 0) throw new Error('macOS returned an invalid idle duration');
    var event = {ts: Date.now() / 1000, mono: Number($.NSProcessInfo.processInfo.systemUptime), app: bundle, app_name: appName, title: title, document: document, idle: idle, locked: locked, accessibility: trusted, desktop_context: context};
    var data = $(JSON.stringify(event) + '\n').dataUsingEncoding($.NSUTF8StringEncoding);
    $.NSFileHandle.fileHandleWithStandardOutput.writeData(data);
    if (!once) $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(2));
  } while (!once);
}
