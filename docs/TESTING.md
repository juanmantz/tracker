# Testing without waiting for real hours

## Fast complete workflow

Run `npm test` after `npm ci`. Set `CHROMIUM_PATH` if Chromium is not at `/usr/bin/chromium`.

- Python tests use the actual tracking engine, SQLite, launcher and HTTP handler. They cover app switches, pause/lock, idle removal, sleeping gaps, DST week boundaries, corrections and private-browser exclusion.
- Recognition tests cover linked files surviving renames, native document paths, ambiguous names, narrower names, weak conversation suggestions and saved corrections. Generic activity assignments remain scoped to that record.
- OAuth/MCP tests start an isolated real HTTP provider and drive the production connection client. They verify registration, PKCE, callback state and issuer, token refresh rotation, private credential storage, actual `record_measurement` Worked commands, zero corrections, revision conflicts and pending request recovery after restart.
- Browser tests drive the actual local application through sign-in, project load, suggestion confirmation, generic activity assignment, direct sync, repeat sync, weekly settings and disconnect. The isolated provider replaces the remote Dreams account; the app's APIs, client and database are real.
- Extension contract tests execute production code with controlled Chrome fixtures. The installed 0.6 collector is compiled Swift and is exercised on a macOS runner; the earlier JXA path remains a development fallback.

`npm run test:sync-ui` runs the connection/project/sync journey on its own. Screenshots and machine-readable reports are saved in `artifacts/`. Production has no synthetic native event injection endpoint.

## Accounting replay

The Settings workday test feeds eight fictional hours through the actual engine in a separate in-memory database. It checks exact project partitions, not whether a displayed timer increases. The eight-hour input includes app switches, idle, lock, coding, unknown activity and pause. This can verify accounting immediately without polluting personal history.

## What still needs a Mac

Finder launch, Gatekeeper behavior, native Accessibility and document availability require a Mac. The user has observed their installed timer increasing, but that alone does not establish correct document recognition or remote synchronization.

For the installed 0.5 app, sign in through **Projects → Connect Dreams**, confirm one actual activity's destination, and **Sync assigned hours**. The local status reports the sent seconds and week. In Dreams, the destination's Worked measurement should show source `Dreams Time` and that period. Repeat sync should keep the same total. This validates the real account connection without collecting hours first.

No artificial activity or fictional Worked measurements are sent to the user's live Dreams map by these tests. The deployed worker's OAuth and measurement contracts were inspected read-only; its consent/login path has not been observed on the user's Mac.

## Installer coverage

The launcher tests mock Mac `open`/`ditto` and use a Linux runtime fixture. They check cold install, paths containing spaces, readiness, checksum validation, repeat-launch reuse, corruption/stale-lock recovery, version replacement and preservation of data and pairing tokens.

The universal package includes checksum-verified standalone CPython 3.12.15 archives. The native sensor runs using macOS's built-in JXA, with an optional compiled Swift collector for developers. The package is currently unsigned and not notarized.

## Native installer (0.6)

The Mac workflow compiles universal arm64/x86_64 native window and collector executables, bundles both checksum-verified CPython archives, and uses Apple's pkgbuild/productbuild. It modifies the unsigned PKG with an 11-project fictional catalog using the same personalization code as the owner's private installer, installs it through macOS Installer, verifies the app code signature, renders the UI in WKWebView, and observes at least two actual samples from the installed collector. The snapshot must contain the 11 preloaded projects with no Dreams login.

The first real Mac run exposed a Ref-bridging failure in the earlier JXA collector. Shipping the compiled Swift collector removed that scripting dependency. The complete installed native app now runs with its own window and Dock icon. Raw personal bootstrap catalogs are excluded from Git and CI; the app payload and BOM remain unchanged during personalization.

This establishes actual macOS installation/startup/window/capture behavior. User-specific Gatekeeper, Accessibility approval and live account consent remain separate OS/account actions. The package is not notarized.

## Live connection regression (0.6.1)

A real macOS request to Dreams' public discovery endpoint reproduced the user's pre-sign-in HTTP 403 with Python-urllib's defaults. An honest `DreamsTime` User-Agent and `Accept: application/json` received HTTP 200 and valid discovery metadata. The production client now supplies those headers for discovery, registration, token exchange, refresh and MCP; MCP keeps its JSON/SSE Accept header.

CI checks the actual client against live public discovery. The installed-app test also drives the exact Connect API through live discovery and public PKCE client registration, asserting the resulting browser authorization URL, scopes and loopback callback. It does not authenticate an account, obtain tokens, read a live map or write measurements. The isolated provider requires the same headers throughout the full OAuth/refresh/MCP/sync journey and verifies that a denied setup reports its step without exposing remote secrets or losing recorded time.

The installer test starts the prior service with two fictional minutes stored locally, then installs the update and verifies the new version starts, those minutes remain, and pairing and installation identifiers are preserved. Live account consent and arrival of the user's real hours still require verification on their account.


## Unattended operation (0.7)

`python3 -m unittest tests.test_automatic -v` accelerates a full eight-hour day through the real SQLite tracker and HTTP OAuth/MCP contract. It switches projects remotely, counts mouse-only activity, removes the full lunch idle tail, overrides focus for a known file, loses connectivity and a committed response, restarts the connection, applies daily corrections and verifies exact measured totals with no duplication. Other cases cover bounded generic-chat corrections, file renames, invalid control data, paused automation, sensor recovery, and the live provider's 20,000-character field limit. No real account receives fixture hours.

The mac-installer job installs the full package, runs the native window/collector, then kills the collector and service deliberately. It checks sensor watchdog recovery, launchd recovery without clicking anything, explicit Quit, reopening, and preservation of existing saved history. Evidence is in `autonomy-check.json` in the Mac proof artifact. These checks distinguish native process recovery from simulated attribution tests.

The earlier manual Sync walkthrough is retained above as historical context; it is not required for 0.7 operation or acceptance. Daily semantic review is a ChatGPT automation using the archived coordination records described in AUTOMATION.md.
