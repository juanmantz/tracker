const form = document.querySelector("form");
const token = document.querySelector("#token");
const browser = document.querySelector("#browser");
const capture = document.querySelector("#capture");
const status = document.querySelector("#status");
chrome.storage.local.get(["token", "browser", "captureChatGPT", "status"]).then(v => {
  token.value = v.token || ""; browser.value = v.browser || "chrome"; capture.checked = !!v.captureChatGPT;
  status.textContent = v.status || "Not paired yet";
});
form.addEventListener("submit", async event => {
  event.preventDefault();
  await chrome.storage.local.set({ token: token.value.trim(), browser: browser.value, captureChatGPT: capture.checked });
  status.textContent = "Saved. Open a normal browser tab; the tracker should see it within a few seconds.";
});
