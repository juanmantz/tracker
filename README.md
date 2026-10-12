# Dreams Time

## Update and connect

1. Unzip **Dreams-Time-Update-0.5.zip** and open **Dreams Time.app**. The update reuses your installed private runtime and keeps your existing data. For a new installation, use **Dreams-Time-Mac-0.5.zip** instead.
2. Open **Projects → Connect Dreams** and sign in to your existing Dreams account. The app loads projects and other work assets directly.
3. Check the project assignments and click **Sync assigned hours**. Assigned weekly totals appear in Dreams as actual Worked hours. Unassigned time stays local.
4. Optional: enable **Automatically sync assigned hours from completed weeks** in Settings. This runs while the app is open and includes later corrections.

The full download includes Apple Silicon and Intel runtimes. Python, Homebrew and Xcode are not required. Opening the update replaces the older running tracker and preserves its database. The app installs in your user Applications folder.

If macOS blocks the unsigned app, use **Privacy & Security → Open Anyway**. Window names and document identities require macOS Accessibility permission, accessible from Settings. Pause and quit are available in the app.

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

The OAuth/MCP workflow is tested against an isolated HTTP provider, using contracts inspected in the live Dreams worker. This Linux build cannot verify Finder/Gatekeeper, macOS permissions, or the final sign-in on your Mac. No fictional hours were written to your real Dreams account.

Activity stays in `~/Library/Application Support/Dreams Time`. See [docs/TESTING.md](docs/TESTING.md) and [docs/DEVELOPER.md](docs/DEVELOPER.md) for validation and source setup.
