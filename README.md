# Dreams Time

## Install

Download **Dreams Time.pkg** and open it with macOS Installer. It installs the complete native app in Applications and opens it. Both Apple Silicon and Intel runtimes are included; Python, Homebrew, Xcode, map imports and pairing tokens are not part of installation. Existing recorded hours and saved associations are kept.

Tracking starts immediately. On macOS 14 or later, allow Screen Recording once to identify projects from the active work window. Screenshots are read with local OCR, then discarded with the full text. Only compact project matches remain. Accessibility additionally supplies document identities and connected-call controls. Closing the app window keeps tracking running; Quit Dreams Time stops it. A login item starts tracking with your Mac and recovers a crashed service. Pause and explicit Quit are respected; reopening resumes after Quit.

The personalized installer includes your current Dreams project catalog. Project recognition and local recording do not require account sign-in.

**Enable saving in Dreams** is optional. It opens your existing Dreams account's authorization page so the app can send assigned hours there. After authorization, project hours save every five minutes, including the current week, and failed saves retry automatically. This does not connect a ChatGPT account or import its history.

The native app and collector are compiled as universal Mach-O executables. The installer uses Apple's pkgbuild/productbuild and is tested by installing it and running the bundled app on a Mac runner. It is currently ad-hoc signed and not notarized; macOS may require Privacy & Security → Open Anyway for the downloaded installer.

## Project recognition

- Exact Figma file or conversation links in a Dreams asset identify that asset even after the file is renamed.
- A unique, specific project name in a document title or native file path can assign it automatically. Ambiguous matches remain unassigned.
- Project mentions in accessibility text and screenshots remain suggestions. Actual file identity, document title or an explicit reviewed assignment is required before time can publish.
- **Remember file or chat** saves a correction and updates matching recorded history.
- Tell ChatGPT with the Dreams connector “Set my Dreams Time project to [name]”. The Mac reads that instruction within a minute. Known file matches take precedence; otherwise supported work apps follow that project until changed.
- The daily ChatGPT review can correct measured activity and remember specific files. Generic unnamed chats receive bounded corrections, never a global title rule. Uncertain activity is kept without fabricating a project match.

The two-second native activity stream supplies the time. Browser metadata enriches it without adding another clock. Idle, sleep, lock, pause and missing samples do not add work hours.

## Dreams sync

The connection uses the existing Dreams OAuth service with PKCE and a local callback. Credentials stay in a private file on your Mac. Assigned hour totals, dates and device attribution go to Dreams. A private archived review note also holds short document labels, candidate project IDs and measured intervals for daily review. Full URLs, paths, raw conversation text and mouse/keyboard contents are excluded.

Each Mac/asset/week has one stable Worked-hours measurement. Resending replaces that snapshot rather than adding the hours again. Reassigning activity clears the old asset's contribution and updates the new asset. A saved pending request makes retries after an uncertain connection failure repeat-safe. Local-only projects need a Dreams destination before they can be sent.

## Current limits

The tracker measures foreground computer time, not ChatGPT subscription quotas or API billing. It has no continuous personal ChatGPT-account history feed or phone foreground tracker. Your own ChatGPT history export can provide phone conversation context, but message timestamps add zero hours. Desktop conversation recognition uses foreground-window OCR and available Accessibility context. OCR supplies review candidates; a project name alone never establishes the work. ChatGPT sidebar history and the bottom composer are excluded from OCR. Browser windows are excluded from screenshots.

The OAuth/MCP workflow is tested against an isolated HTTP provider, using contracts inspected in the live Dreams worker. The packaged native window, private runtime, Installer installation and collector are checked on a Mac runner. That does not establish Gatekeeper or Accessibility approval on your own Mac, or your live Dreams sign-in. No fictional hours are written to the real account by tests. The daily review uses the existing Dreams connector, with no separate API key. See docs/AUTOMATION.md for the coordination contract.

Activity stays in `~/Library/Application Support/Dreams Time`. See [docs/TESTING.md](docs/TESTING.md) and [docs/DEVELOPER.md](docs/DEVELOPER.md) for validation and source setup.


### 0.12 attribution correction

A single project name in screen OCR, an accessibility conversation body, or a compact header is a review candidate, not a project assignment. Attribution uses actual document titles/identities, learned files, bounded reviewed decisions, verified call collaborators or explicitly chosen focus. A broad parent/account name alone cannot establish the work. Screen Recording also enables an actual WindowServer title fallback when Accessibility is denied.

The upgrade automatically reclassifies older inferred assignments while preserving measured seconds, explicit assignments, learned files and reviewed decisions. The Mac then replaces its own stable whole-hour weekly totals, including zero corrections. Partial hours remain local.

Device notes include a separate `assignment_audit` for the entire current week: per-project seconds, completed hours, retained seconds and a bounded document/app/reason breakdown with explicit omitted-source counts. The review queue cannot crowd out that audit. Very large project/source lists have explicit omission counts; complete evidence remains on the Mac. On the Projects screen, “What counted” exposes the full local document breakdown. No raw screenshot, full OCR transcript, click locations or keystrokes are retained.
