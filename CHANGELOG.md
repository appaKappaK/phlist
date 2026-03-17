# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [1.8.0] - 2026-03-16

### Added
- **Combine Selected** — Ctrl+click to multi-select lists in the Library, then merge them into one deduplicated list with combined credits and sources
- **Refresh Credits** — retroactively extract author credits from source URLs for older saved lists that were created before auto-credits existed
- **Fetch cache** — re-combining after adding new sources only downloads the new ones; previously fetched content is reused from an in-memory cache (cleared on Clear All)
- **Source dedup** — duplicate URLs are blocked when adding sources; the source list displays sorted alphabetically
- **Splash screen** — branded loading screen with the app logo and busy cursor while the GUI initializes
- **Logging** — rotating debug log file at `~/.db/piholecombinelist.log` (1 MB, 3 backups) for troubleshooting; all modules instrumented
- **Update List** — re-fetch all source URLs for a saved list and re-combine in one click; saved content, domain count, and stats are updated in the database automatically
- **Update All Lists** — bulk-refresh every saved list that has URL sources with a progress bar showing per-list status
- **Auto-rehost** — if an updated list is currently being hosted, the served content refreshes immediately without needing to stop and restart
- `Pillow` dependency for splash screen logo rendering
- Stress tests (`test_stress.py`) and dev probe scripts (`scripts/probe_*.py`)
- Asset generation scripts (`scripts/agent/`) for SVG rendering, PNG resizing, and image info

### Fixed
- Copy, Save File, Export, and Host now output the full list content instead of the truncated viewer preview
- Remaining "Adlists" references in tooltips and messages updated to match Pi-hole's "Lists" tab

## [1.7.1] - 2026-03-15

### Added
- **Hover tooltips** — all buttons and key inputs now show descriptive tooltips on mouseover
- **Paste box placeholder** — gray hint text in the paste area that clears on focus
- **Rename list** — rename saved lists in the Library tab

### Changed
- Renamed "Serve" to "Host" throughout the UI, tooltips, and documentation
- Removed redundant paste box label (placeholder text is sufficient)

### Fixed
- Paste buttons no longer get cut off when combining large lists

## [1.7.0] - 2026-03-14

### Added
- **Multi-path hosting** — the HTTP server now supports hosting multiple lists simultaneously at different URL paths; enables Pi-hole group management with separate lists per device group
- **Custom host filename** — name the hosted file in the Combine tab (e.g. `general` -> `/general.txt`) instead of the fixed `/blocklist.txt`
- **Host from Library** — host any saved list directly from the Library tab with its own URL, without needing to re-combine

## [1.6.0] - 2026-03-13

### Added
- **Settings persistence** — port and Blocklist/Allowlist choice now saved to the local database; restored automatically on next launch
- **Source metadata** — when saving a combined list to the library, the source URLs are stored alongside it; loading the list back into the Combine tab restores the individual URLs so you can see where it came from and re-fetch fresh data

### Changed
- **gui/ package refactor** — monolithic `gui.py` split into `gui/app.py`, `gui/combine_tab.py`, `gui/library_tab.py`, `gui/settings_tab.py`; no user-visible change

## [1.5.0] - 2026-03-12

### Added
- New **Settings** tab — Blocklist/Allowlist toggle (updates output header and window title), server port field, desktop shortcut installer
- **Auto-credits** — Extract URLs now detects author names from GitHub, GitLab, Bitbucket, Codeberg, jsDelivr CDN, and surrounding line text; written as `# Credits: ...` in the combined list header
- URL extractor handles all paste formats: plain lists, markdown tables (backtick-wrapped URLs), Pi-hole dashboard, mixed prose

## [1.4.1] - 2026-03-11

### Added
- Red/green indicator next to Host List button shows server state at a glance

## [1.4.0] - 2026-03-10

### Added
- **Host List** — built-in LAN HTTP server hosts the combined list so Pi-hole can pull it via gravity; stops cleanly on app close

## [1.3.3] - 2026-03-09

### Fixed
- Virtual root now shows as Root vs user folders — fixes delete being blocked when a folder named "Root" existed in the database

## [1.3.2] - 2026-03-08

### Added
- Save to Library dialog: `+ New Folder` option lets you create a folder inline without leaving the dialog
- Creating or renaming a folder to "Root" is now blocked (reserved name)

## [1.3.1] - 2026-03-07

### Fixed
- App window and taskbar now show the shield icon instead of the generic X11 logo

## [1.3.0] - 2026-03-06

### Added
- Progress bar and per-source status label during Combine All

### Fixed
- Black/blank Save to Library dialog on Linux

## [1.2.0] - 2026-03-05

### Added
- **Extract URLs** button — paste Pi-hole's Lists dashboard page and pull all subscription URLs automatically

## [1.1.2] - 2026-03-04

### Fixed
- Parser now handles ABP/AdGuard format (`||example.com^`) and pipe-delimited lines (`example.com | comment`) — previously these were silently dropped

## [1.1.1] - 2026-03-03

### Added
- Desktop shortcut installer (`phlist-desktop`)
- Dynamic User-Agent in fetcher (`PiHoleCombineList/<version>`)

### Changed
- Commands renamed from `pihole-gui` to `phlist` to avoid collision with official Pi-hole CLI

## [1.1.0] - 2026-03-02

### Added
- App icon (SVG + `.desktop` entry) for Linux launcher integration

## [1.0.1] - 2026-03-01

### Fixed
- Runtime bug fixes and code cleanup

## [1.0.0] - 2026-02-28

### Added
- Initial release: Combine tab, Library tab, SQLite-backed folder/list storage
- Fetch blocklists from URLs or local `.txt` files
- Paste raw blocklist text directly into the app
- Parses plain domains, hosts-file, ABP/AdGuard, and pipe-delimited formats
- Deduplicates across all sources
- Save combined lists to a local library organized in folders
- Dark mode desktop GUI (customtkinter)
