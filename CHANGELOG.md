# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [1.8.3] - 2026-03-17

### Added
- **Settings tab overhaul** — two-column card layout with visible bordered cards for each section; cards: LIST TYPE, SERVER, DESKTOP, COMBINE DEFAULTS (timeout + filename), APPEARANCE, LIBRARY stats, LOG viewer, DATA
- **Export Database** — saves a backup copy of `phlist.db` to any location via file dialog
- **Import Database** — restores a backup live into the running app using SQLite's backup API; Library tab refreshes immediately, no restart needed
- **Open Data Folder** — opens `~/.local/share/phlist/` in the system file manager from the Settings tab
- **Security — SSRF protection** — `fetch_url()` now rejects responses whose final URL (after redirect) resolves to a private or loopback IP address
- **Security — response size cap** — fetched responses exceeding 50 MB (via `Content-Length` header or actual body size) are rejected to prevent memory exhaustion
- **Security — null-byte stripping** — null bytes (`\x00`) are removed from all fetched content before parsing or storage
- **Security — unicode sanitization** — bidi-override characters (U+202A–U+202E, U+2066–U+2069) and zero-width characters (U+200B–U+200D, U+FEFF) are stripped from folder names, list names, and other user-supplied strings on write
- **Test suite expanded** — 106 → 123 tests; new coverage: `rename_list`, sort-order verification, empty-combiner edge cases, deduplicator case-sensitivity, empty-file fetch, mocked URL success, all four security hardening paths, parser edge cases, updater edge case

### Changed
- Settings tab library stats now displayed in a compact 2×2 grid (was 4 stacked labels)
- DATA card buttons renamed "Export Database…" / "Import Database…" (previously stubs labeled "Export Library…" / "Import Library…")

## [1.8.4] - 2026-03-17

### Changed
- **"Update Selected" → "Re-fetch Sources"** — button renamed to clarify it pulls fresh data from source URLs
- **"Update" → "Re-fetch"** — single-list update button renamed for consistency
- Unified duplicate copy-to-clipboard logic in Library tab into a single `_copy_content()` method
- Removed unused `ListServer.start()` compatibility wrapper
- Internal method renames for clarity (`_update_all` → `_refetch_selected`, etc.)
- Added cross-reference comments documenting the updater vs combine_tab pipeline relationship

## [1.8.2] - 2026-03-17

### Changed
- Internal package renamed from `piholecombinelist` to `phlist` — consistent with the CLI
  command; data directory, database, and log file all migrate automatically on first launch
- `pyproject.toml` package name updated to `phlist`; entry points and asset references updated

## [1.8.1] - 2026-03-17

### Added
- **Settings tab overhaul** — two-column layout with 6 new sections:
  - **Appearance** — Light/Dark/System theme toggle, persists across restarts (no theme flash on launch)
  - **Library stats** — folder/list/domain counts and database size
  - **Log viewer** — last 15 log lines inline + Open Log File button (opens in system editor)
  - **Fetch timeout** — configurable HTTP timeout (1-300s, default 30s), applied to Combine and Update
  - **Default host filename** — pre-fills the host filename entry on the Combine tab
  - **Export/Import** — stub buttons (coming in a future release)
- **Timestamps in Library** — each list button shows the created/updated date (`3/17/26 4:11 AM`); opening a list shows full created and updated timestamps in the content viewer
- **View All Sources** — when the sources panel overflows (30+ entries), a clickable link opens the full list in your system text editor
- `tests/test_deduplicator.py` — dedicated unit tests for `Deduplicator`

### Changed
- Data directory moved from `~/.db/` to `~/.local/share/piholecombinelist/` (XDG standard); existing files are auto-migrated on first launch
- `_DISPLAY_LIMIT` centralised as a single module-level constant shared between Combine and Library tabs
- Log backup count reduced from 3 to 1 (1 MB rotating, 1 backup)
- "Update All Lists" renamed to "Update Selected" — now operates only on the currently selected lists, matching how Refresh Credits works

### Fixed
- Clipboard operations now show an error dialog on failure instead of crashing (X11/Wayland)
- Right-click Copy in Library viewer now shows a "Copied" confirmation (was silent)
- Source type detection uses `startswith(("http://", "https://"))` instead of `startswith("http")`
- `Deduplicator.domains` property now returns a copy, preventing external mutation of internal state
- X11 `BadAlloc` crash when loading a combined result built from many URL sources: sources panel now caps at 30 rendered rows (overflow shown as a count label; all sources still used by Combine All)
- `_update_output` no longer splits the full content string to count lines; uses an efficient newline scan to avoid a memory spike on large lists
- `_copy_serve_url` now shows an error dialog on clipboard failure instead of raising `TclError`

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
