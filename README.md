# Dreams Time

## Install

Download **Dreams Time.pkg** and open it with macOS Installer. It installs the complete native app in Applications and opens it. Both Apple Silicon and Intel runtimes are included; Python, Homebrew, Xcode, map imports and pairing tokens are not part of installation. Existing recorded hours and saved associations are kept.

Tracking starts immediately. Allow macOS Accessibility when prompted to detect document names and project context. Closing the app window keeps tracking running; Quit Dreams Time stops it. A user login item restarts tracking on the next Mac login and honors the saved paused state.

The personalized installer includes your current Dreams project catalog. Project recognition and local recording do not require account sign-in.

**Enable saving in Dreams** is optional. It opens your existing Dreams account's authorization page so the app can send assigned hours there. After authorization, completed weeks sync automatically while the tracker runs. This does not connect a ChatGPT account or import its history.

The native app and collector are compiled as universal Mach-O executables. The installer uses Apple's pkgbuild/productbuild and is tested by installing it and running the bundled app on a Mac runner. It is currently ad-hoc signed and not notarized; macOS may require Privacy & Security → Open Anyway for the downloaded installer.

## Project recognition

- Exact Figma file or conversation links in a Dreams asset identify that asset even after the file is renamed.
- A unique, specific project name in a document title or native file path can assign it automatically. Ambiguous matches remain unassigned.
- Imported/submitted conversation text and optional visible ChatGPT desktop text suggest projects. Suggestions need confirmation because visible text can include sidebar content.
- **Remember file or chat** saves a correction and updates matching recorded history.
- A generic desktop title such as `ChatGPT` can be assigned for that recorded activity, or to a project for a 30-minute session. A generic title cannot identify future conversations.

The two-second native activity stream supplies the time. Browser metadata enriches it without adding another clock. Idle, sleep, lock, pause and missing samples do not add work hours.

## Dreams sync

The connection uses the existing Dreams OAuth service with PKCE and a local callback. Credentials stay in a private file on your Mac. Only assigned hour totals, dates and device attribution go to Dreams; titles, URLs and conversation text do not.

Each Mac/asset/week has one stable Worked-hours measurement. Resending replaces that snapshot rather than adding the hours again. Reassigning activity clears the old asset's contribution and updates the new asset. A saved pending request makes retries after an uncertain connection failure repeat-safe. Local-only projects need a Dreams destination before they can be sent.

## Current limits

The tracker measures foreground computer time, not ChatGPT subscription quotas or API billing. It has no continuous personal ChatGPT-account history feed or phone foreground tracker. Your own ChatGPT history export can provide phone conversation context, but message timestamps add zero hours. Desktop conversation recognition depends on what the ChatGPT app exposes through Accessibility.

The OAuth/MCP workflow is tested against an isolated HTTP provider, using contracts inspected in the live Dreams worker. The packaged native window, private runtime, Installer installation and collector are checked on a Mac runner. That does not establish Gatekeeper or Accessibility approval on your own Mac, or your live Dreams sign-in. No fictional hours were written to your real Dreams account.

Activity stays in `~/Library/Application Support/Dreams Time`. See [docs/TESTING.md](docs/TESTING.md) and [docs/DEVELOPER.md](docs/DEVELOPER.md) for validation and source setup.
