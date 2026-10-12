# Dreams Time development

The shipping app runs a Python standard-library loopback service, a compiled macOS activity sensor and a local dashboard. It uses an optional Chromium extension for focused browser context. Node/Playwright are development dependencies only.

```bash
python3 -m dreamstime.server --no-sensor
npm ci
npm test
```

On macOS omit `--no-sensor` to run the built-in scripting collector. The old `Start.command` path optionally compiles the Swift collector and requires Apple's developer tools; normal users should use the bundled `.app` instead.

## Modules

- `core.py`: SQLite, one native activity clock, week boundaries, association rules, scoped manual assignments, reporting.
- `recognition.py`: explainable matching against an imported Dreams catalog. Linked identities and unique document names can assign; conversation text only suggests.
- `connection.py`: Dreams OAuth registration, PKCE, state/issuer checks, offline token rotation and streamable HTTP MCP. It accepts a custom origin only for isolated tests.
- `sync.py`: frozen assigned totals, durable pending requests, conflict handling, weekly completed-period synchronization.
- `dreams.py`: `build_worked_batch` creates `record_measurement` commands with Worked basis and Own scope. The older `build_batch` Time-node adapter remains for regression coverage; current UI/export/sync use Worked measurements.
- `account.py`: user-supplied ChatGPT exports add local context and zero time.
- `status.py`/`quickcheck.py`: actual process/sample/saved-time state and the native observation check.

## Sync contract

Production origin is `https://dreams.checklists.workers.dev`, resource `/mcp`, native redirect `http://127.0.0.1:43123/oauth/callback`. Discovery supplies authorization, registration and token endpoints. Requested scopes: `mcp:read mcp:write offline_access`. The native public client uses `token_endpoint_auth_method: none` and PKCE S256. Local bearer authentication remains required for all dashboard API actions; only the state-protected OAuth callback is unauthenticated.

`record_measurement` carries an asset ID plus a stable device/asset/week measurement ID, `metric: workedHours`, an hours quantity, `basis: Worked`, a Custom Monday–Sunday period, `observedAt`, `source` and `scope: Own`. It replaces a snapshot; it is not an additive transaction or a capacity allocation. Corrections can write zero. A pending batch retains its request ID and observedAt through retries and restarts. Explicit rejection clears that pending request; unknown outcomes keep it.

The app sends only assigned totals. A Sync action freezes the report server-side while native collection continues. The weekly option sends completed weeks and revisits prior periods for corrections while the app is open. Local-only projects are rejected until assigned to actual Dreams destinations. Unassigned activity is omitted and displayed locally.

The live worker contracts were inspected through the connected Cloudflare/Dreams tools. The test provider in `tests/dreams_provider.py` is isolated and supports a deliberately failed response after committing a write to verify deduplication. Do not point fictional test records at a user's Dreams account.

## Storage/privacy

Local activity is in `~/Library/Application Support/Dreams Time/activity.sqlite`. The directory and pairing token are user-private; OAuth credentials are atomically written with mode 0600. Tokens never enter dashboard snapshots, diagnostics, console request logs or packages. Native AXDocument identity is available only with Accessibility; browser titles/documents remain excluded from native capture and require fresh focused extension context. URLs discard credentials, queries and fragments. Optional bounded ChatGPT static text skips editable fields and drafts; project-hint IDs can be retained with a segment while its raw text stays in memory.

The app has no continuous ChatGPT account/phone activity API and does not measure subscription quotas. Conversation exports and visible static text are project evidence, not a duration source.

## Packaging

`scripts/package-mac.py` builds a universal archive using the two verified standalone Python archives in `/tmp`. `--update-only` omits those runtimes and reuses the installed one. The launcher compares app versions, shuts down an older local server with its existing token, installs the new code, and starts it with the same data directory. Neither archive contains local activity or credentials.

See `docs/TESTING.md` for test layers and unverified physical-Mac behavior.

## Native shipping build

`native/DreamsTimeApp.swift` owns the native window, standard app/Edit menus, account-authorization navigation, clipboard/save dialogs and app quit. The launch script runs in headless installed mode; its private HTTP service is embedded in WKWebView. Both architectures of `ActivitySensor.swift` are compiled and shipped, with native AXDocument support. The scripted collector is a fallback for developer builds only.

`scripts/build-installer-mac.sh` builds the universal app, ad-hoc signs it, and invokes pkgbuild/productbuild. Installer postinstall preserves the activity directory, writes the minimal project catalog privately, installs a per-user login agent and opens the app. `scripts/personalize-installer.py` replaces only the existing catalog in the Scripts cpio archive of an unsigned Apple-built XAR. It preserves all other archive bytes, including the app payload and BOM, and validates the reconstructed checksums.

The owner's real catalog belongs in `.data/installer-projects.json` (Git-ignored) and the private delivered PKG. Public CI uses a fictional catalog to test this exact packaging and bootstrap path. Never add the owner's map or credentials to source or public build artifacts.
