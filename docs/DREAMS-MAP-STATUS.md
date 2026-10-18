The Dreams map distinguishes permission recovery, project attribution and published hours.

The header reads archived `dreamstime/review/v1` device notes already delivered through the authenticated map. It displays matched and unassigned measured activity separately from completed project hours. It never renders document titles, executes report contents, follows report links or converts missing measurements to worked time. A stale/offline report is neutral. Duplicate device notes use the latest timestamp. Totals carry their own calculation time.

The weekly worked-hours goal says “Waiting for recorded hours” when its contributors have no measurement in the selected period. Actual missing configuration retains the original configuration warning. Other goals and financial values are unaffected. Existing map polling refreshes the status automatically.

The production content-only deployment on 18 October 2026 is `0367b1228c834ade90dc8322cfd9f96c`, using `/assets/index-79adf43f2e6f.js`. Its SHA-256 is `79adf43f2e6fca3ad2876c535c482fc80c55e33298a1a36813a7b8ba092f4785`. Deployed module readback matches the browser-tested bundle. Accounting, storage, authentication and deployment wrapper modules retain their prior hashes. No owner measurements or budgets were changed by this deployment.

`patch-map-ui.mjs` reproduces the asset update from the exact preceding deployed asset module and refuses changed input. It retains the old immutable JavaScript URL and gives new code a new URL. Existing open tabs need one page reload to load the new bundle; no Mac reinstall is needed.

Verification: `node tests/map-tracker-status.test.cjs` covers no-report, stale, denied access, paused, transfer error, invalid/future report, duplicate device, retained totals and actual published measurements. Browser verification with the real compiled map and an intercepted local map response covered the waiting-hours message, matched/unassigned display, no JavaScript errors and automatic report refresh. Anonymous production HTTP verification was blocked with 403; authenticated production browser rendering was not directly observed.

Known limit: status visibility does not reconstruct historical project context. The first fresh 0.10.0 report identified a specific external Figma document automatically, while compact context cards remained absent. Keep generic historical activity unassigned without sufficient evidence.
