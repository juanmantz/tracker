# Local inspector direction

Purpose: make tracking observable immediately and make time attribution reviewable.
Direct implementation is implied by the user's request to build and test the companion.

Live Refero searches for developer tooling and time tracking returned NO_SUBSCRIPTION.
Fallback references: Refero typography.md and craft-details.md, plus the user's explicit need to verify collection without waiting.

Reference lock: neutral local utility, light canvas, system font, compact rows, thin borders,
green reserved for confirmed collector health/assigned time; amber for uncertain attribution.
No external assets or fonts. The defining interaction is an isolated simulated workday with
expected-versus-observed assertions and a live activity/evidence inspector.

| Decision | Source | Role / reason |
| --- | --- | --- |
| System type, 13/16/23/33px, tabular numerals | typography.md | Functional work tool; stable ticking values |
| Labels, focus-visible, inline errors, semantic buttons | craft-details.md | Accessible controls and immediately visible failures |
| Weekly totals and attribution rows | User brief | Know what project received the hours |
| Separate Live / Test lab | User testing problem | Exercise hours in seconds with no personal-data contamination |
| Explicit collector capability states | User testing problem | Distinguish code simulation from a working native sensor |

## 0.4: status first

User evidence: the owner cannot interpret the dashboard sufficiently to report its status.
Live Refero timer style/screen searches again returned NO_SUBSCRIPTION. Fallback remains
bundled typography and craft guidance, plus the explicit user need for an understandable
recording state. Direct repair is authorized by the ongoing request and this feedback.

Reference lock: a single-purpose desktop utility, no sidebar, white surfaces on a neutral
canvas, system type, one 72px tabular time counter, one 24px status heading and one primary
action. Green means real recording only; amber means a fix is needed. The simulated test
is visible only in Settings and explicitly cannot establish live capture. A neutral pause
state preserves already recorded time. Project bookkeeping lives on a separate tab.

| Decision | Evidence | Reason |
| --- | --- | --- |
| One primary status, no duplicate health/collector/recording cards | User cannot find status | Remove competing conclusions |
| HH:MM:SS counter with Recorded today label | User needs to see activity | Make sub-minute changes evident |
| Start/Pause/Resume/Restart as one contextual action | User wants little setup | Give a concrete next action |
| State-specific plain descriptions | User cannot understand terminology | Explain consequences without process jargon |
| Tracking / Projects / Settings tabs | User dislikes dense dashboard | Keep the main view about collecting time |
| Details-only samples, error traces, export and simulated tests | User feedback; craft functional clarity | Debug material available on demand |

## 0.6: installation and account authorization

The user's explicit requirement is a downloadable installable Mac app with very little setup. The existing utility interface remains the locked build target. Live Refero onboarding research is unavailable (NO_SUBSCRIPTION); bundled craft guidance and the user's observed friction guide the interaction repair.

- Use the standard macOS Installer journey and one complete PKG rather than asking the user to choose full vs update archives.
- Open a native app window with a Dock icon; keep service addresses and browser setup out of the primary flow.
- Preload only work asset IDs/names/links in the owner's private installer, so local project recognition can start without sign-in. Never put that catalog into the public source repo.
- Label the optional account action Enable saving in Dreams and explain the consequence: authorize sending assigned hours to the existing Dreams account. It is not needed to record activity.
- Enable completed-week syncing after the account grants authorization. The user can disable it in Settings.
- Delegate OS permission and package installation controls to macOS. These remain standard system interactions.


## 0.7: unattended operation

The user explicitly wants collection, attribution, saving and daily review without repeated actions. Refero status/sync research again returned NO_SUBSCRIPTION; retain the existing reference lock and make behavior/copy changes only. The main view shows automatic save state and the last save time. Save now and manual corrections remain optional recovery controls. Settings has one automatic-saving switch; default is on after the existing account authorization. Technical coordination records stay out of normal product flows.
