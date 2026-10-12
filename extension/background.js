const ENDPOINT = "http://127.0.0.1:43123/api/browser";
let chain = Promise.resolve();

// Serialized requests prevent a slower old tab request overwriting a newer tab.
function queue(message, sender) {
  chain = chain.catch(() => {}).then(() => publish(message, sender));
  return chain;
}
async function publish(message, sender) {
  const { token, browser = "chrome" } = await chrome.storage.local.get(["token", "browser"]);
  if (!token) return;
  let payload = { browser, focused: false };
  const window = await chrome.windows.getLastFocused({ populate: true });
  const tab = window.tabs?.find(tab => tab.active);
  if (window.focused && tab && !tab.incognito) {
    payload = { browser, focused: true, private: false, url: tab.url || "", title: tab.title || "" };
    // A stale message from a background tab cannot contribute conversation content.
    if (sender?.tab?.id === tab.id && sender.tab.url === tab.url && message?.capture_context) {
      payload.prompts = message.prompts;
      payload.capture_context = true;
    }
  } else if (tab?.incognito) payload.private = true;
  try {
    const response = await fetch(ENDPOINT, { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify(payload), signal: AbortSignal.timeout(2000) });
    const text = response.ok ? "Connected" : "Pairing failed — check the local token";
    await chrome.storage.local.set({ status: text, lastContact: Date.now() });
    await chrome.action.setBadgeText({ text: response.ok ? "" : "!" });
  } catch {
    await chrome.storage.local.set({ status: "Tracker offline — open Start.command", lastContact: Date.now() });
    await chrome.action.setBadgeText({ text: "!" });
  }
}
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (message.type !== "heartbeat") return;
  queue(message, sender).then(() => reply({ ok: true })).catch(() => reply({ ok: false }));
  return true;
});
chrome.tabs.onActivated.addListener(() => queue());
chrome.tabs.onUpdated.addListener((_id, change) => { if (change.url || change.title) queue(); });
chrome.windows.onFocusChanged.addListener(() => queue());
chrome.runtime.onStartup.addListener(() => queue());
chrome.runtime.onInstalled.addListener(() => { chrome.alarms.create("health", { periodInMinutes: .5 }); queue(); });
chrome.alarms.onAlarm.addListener(() => queue());
chrome.action.onClicked.addListener(() => chrome.runtime.openOptionsPage());
