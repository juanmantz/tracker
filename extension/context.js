// Never read forms, drafts, keyboard events, passwords, or arbitrary page text.
(() => {
  async function heartbeat() {
    if (document.visibilityState !== "visible") return;
    try {
      const { captureChatGPT = false } = await chrome.storage.local.get("captureChatGPT");
      const onChatGPT = ["chatgpt.com", "chat.openai.com"].includes(location.hostname);
      const prompts = captureChatGPT && onChatGPT
        ? [...document.querySelectorAll('[data-message-author-role="user"]')]
            .slice(-5).map(node => node.innerText.slice(0, 1000)) : undefined;
      await chrome.runtime.sendMessage({ type: "heartbeat", prompts, capture_context: captureChatGPT && onChatGPT });
    } catch { /* Extension may have been reloaded. */ }
  }
  setInterval(heartbeat, 2000);
  document.addEventListener("visibilitychange", heartbeat);
  heartbeat();
})();
