# Pi-hole Combined Blocklist Generator

A Python desktop app that fetches, parses, and deduplicates multiple Pi-hole blocklists from URLs, local files, or pasted text — then combines them into a single optimized list ready to push directly to Pi-hole.

## Features

- Fetch blocklists from URLs or local `.txt` files
- Paste raw blocklist text directly into the app
- **Extract URLs** from pasted text in any format — plain lists, markdown tables, Pi-hole dashboard — pulls all `http/https` URLs automatically
- **Auto-credits** — when extracting URLs, detects the author/username from GitHub, GitLab, Bitbucket, Codeberg, jsDelivr CDN, and surrounding line text; credited names appear in the combined list header
- Parses all common blocklist formats:
  - Plain domains: `example.com`
  - Hosts-file: `0.0.0.0 example.com` / `127.0.0.1 example.com`
  - ABP/AdGuard: `||example.com^` (with optional options or path)
  - Pipe-delimited: `example.com | comment`
- Deduplicates across all sources — shows unique domain count and duplicates removed
- Progress bar and per-source status during combine
- Save combined lists to a local library organized in folders
- Load saved lists back into the combiner to merge with new sources
- **Host List** — hosts combined lists over HTTP on your LAN so Pi-hole can pull them directly via gravity; name each hosted file (e.g. `general.txt`, `tvs.txt`) so multiple lists can be hosted simultaneously at different URLs for Pi-hole group management
- **Host from Library** — host any saved list directly from the Library tab without re-combining
- Dark mode desktop GUI (customtkinter)
- Window and taskbar icon
- Install desktop shortcut / launcher entry (Linux)

## Installation

```bash
git clone https://github.com/appaKappaK/PiHoleCombineList.git
cd PiHoleCombineList
pip install -e .
```

## Usage

```bash
phlist
```

The app opens with three tabs:

- **Combine** — add sources (URL / file / paste), click *Combine All*, then copy, save, export, or push to Pi-hole
- **Library** — browse saved lists organized in folders, view contents, export, or load back into the combiner
- **Settings** — Blocklist/Allowlist toggle (switches whether the combined output is labeled as a blocklist or allowlist — use Allowlist mode when combining domain whitelists for Pi-hole's allow list), server port, desktop shortcut installer (all settings persist across restarts)

> **Note:** The Blocklist/Allowlist toggle only changes the output header label — it does not affect how Pi-hole processes the list. Blocklists should be added to Pi-hole's **Adlists** page; allowlists should be added to the **Whitelist** section on Pi-hole's Domains page.

### Pushing to Pi-hole

1. Build your combined list in the Combine tab
2. Optionally type a filename (e.g. `general`) — leave blank for the default `blocklist.txt`
3. Click **Host List** — the `●` indicator turns green and a URL appears (e.g. `http://YOUR.IP.GO.HERE:8765/general.txt`)
4. Copy the URL and paste it into Pi-hole's **Adlists** page
5. Run **Update Gravity** in Pi-hole — it fetches and caches the list
6. Click **Stop Hosting** or close the app — Pi-hole retains the list from its gravity cache

> Pi-hole and your PC just need to be on the same local network. The server defaults to port **8765**.

> **Tip:** To use Pi-hole's group management, build separate lists (e.g. one for general devices, one for smart TVs) and host each with a different filename. Each URL is a separate adlist entry in Pi-hole that can be assigned to different groups.

### Output format

When you click *Combine All*, the app produces a plain-text file with a short comment header followed by one domain per line, sorted alphabetically:

```
# Pi-hole Combined Blocklist
# Generated: 2026-03-15 14:32:07
# Unique domains: 14267225
# Duplicates removed: 312441
# Lists combined: 8
# Credits: StevenBlack, RPiList, FadeMind, blocklistproject

0-000.store
00-0day.com
000free.us
001.dk
0tracker.com
...
```

The header lines all start with `#` so Pi-hole's gravity parser skips them automatically. Everything below is a bare domain — compatible with Pi-hole's plain-domain blocklist format.

### Desktop shortcut (Linux)

Open the **Settings** tab, click **Install Desktop Shortcut**, or run:

```bash
phlist-desktop
```

This installs the icon and `.desktop` entry so the app appears in your GNOME/KDE launcher.

## Project structure

```
src/piholecombinelist/
  gui/
    app.py            — Main window and tab wiring
    combine_tab.py    — Combine tab + URL/credit extraction helpers
    library_tab.py    — Library tab
    settings_tab.py   — Settings tab
    tooltip.py        — Hover tooltip widget for buttons and inputs
  combiner.py         — Orchestrates fetch → parse → deduplicate
  fetcher.py          — Fetches URLs and local files
  parser.py           — Extracts/validates domains from all supported formats
  deduplicator.py     — Tracks unique domains and duplicate count
  database.py         — SQLite library (folders + saved lists + settings)
  server.py           — LAN HTTP server for Pi-hole gravity integration
  _install_desktop.py — Linux desktop shortcut installer
  assets/             — SVG/PNG icon, .desktop file
tests/
  test_parser.py
  test_fetcher.py
  test_combiner.py
  test_database.py
  test_server.py
```

## Data storage

| Path | Contents | Created by |
|------|----------|------------|
| `~/.db/piholecombinelist.db` | Library (folders, saved lists, settings) | App on first launch |
| `~/.local/share/applications/piholecombinelist.desktop` | Launcher entry | `phlist-desktop` / Settings tab |
| `~/.local/share/icons/hicolor/scalable/apps/piholecombinelist.svg` | SVG icon | `phlist-desktop` / Settings tab |
| `~/.local/share/icons/hicolor/256x256/apps/piholecombinelist.png` | PNG icon | `phlist-desktop` / Settings tab |

The desktop shortcut files are only created if you run the desktop installer — the app itself only writes the database.

## Running tests

```bash
pytest tests/
```

## Requirements

- Python 3.9+
- `requests`
- `customtkinter`
- SQLite (Python stdlib)
- `http.server` / `socket` (Python stdlib — no extra install needed for Host List)

## Recent updates

**v1.7.2**
- Renamed "Serve" to "Host" throughout the UI, tooltips, and documentation
- **Rename list** — rename saved lists in the Library tab
- Removed redundant paste box label (placeholder text is sufficient)

**v1.7.1**
- **Hover tooltips** — all buttons and key inputs now show descriptive tooltips on mouseover
- **Paste box placeholder** — gray hint text in the paste area that clears on focus
- **Layout fix** — paste buttons no longer get cut off when combining large lists

**v1.7.0**
- **Multi-path hosting** — the HTTP server now supports hosting multiple lists simultaneously at different URL paths; enables Pi-hole group management with separate lists per device group
- **Custom host filename** — name the hosted file in the Combine tab (e.g. `general` → `/general.txt`) instead of the fixed `/blocklist.txt`
- **Host from Library** — host any saved list directly from the Library tab with its own URL, without needing to re-combine

**v1.6.0**
- **Settings persistence** — port and Blocklist/Allowlist choice now saved to the local database; restored automatically on next launch
- **Source metadata** — when saving a combined list to the library, the source URLs are stored alongside it; loading the list back into the Combine tab restores the individual URLs (not just the content blob) so you can see where it came from and re-fetch fresh data
- **gui/ package refactor** — monolithic `gui.py` split into `gui/app.py`, `gui/combine_tab.py`, `gui/library_tab.py`, `gui/settings_tab.py`; no user-visible change

**v1.5.0**
- New **Settings** tab — Blocklist/Allowlist toggle (updates output header and window title), server port field, desktop shortcut installer
- **Auto-credits** — Extract URLs now detects author names from GitHub, GitLab, Bitbucket, Codeberg, jsDelivr CDN, and surrounding line text; written as `# Credits: ...` in the combined list header
- URL extractor handles all paste formats: plain lists, markdown tables (backtick-wrapped URLs), Pi-hole dashboard, mixed prose

**v1.4.1**
- Red/green `●` indicator next to Host List button shows server state at a glance

**v1.4.0**
- **Host List** — built-in LAN HTTP server hosts the combined list so Pi-hole can pull it via gravity; stops cleanly on app close

**v1.3.3**
- Virtual root now shows as `🏠 Root` vs user folders as `📁 name` — fixes delete being blocked when a folder named "Root" existed in the database

**v1.3.2**
- Save to Library dialog: `+ New Folder` option lets you create a folder inline without leaving the dialog
- Creating or renaming a folder to "Root" is now blocked (reserved name)

**v1.3.1**
- App window and taskbar now show the shield icon instead of the generic X11 logo

**v1.3.0**
- Progress bar and per-source status label during Combine All
- Fixed black/blank Save to Library dialog on Linux

**v1.2.0**
- **Extract URLs** button — paste Pi-hole's Adlists dashboard page and pull all subscription URLs automatically

**v1.1.2**
- Parser now handles ABP/AdGuard format (`||example.com^`) and pipe-delimited lines (`example.com | comment`) — previously these were silently dropped

**v1.1.1**
- Desktop shortcut installer (`phlist-desktop`); commands renamed from `pihole-gui` → `phlist` to avoid collision with official Pi-hole CLI
- Dynamic User-Agent in fetcher (`PiHoleCombineList/<version>`)

**v1.1.0**
- App icon (SVG + `.desktop` entry) for Linux launcher integration

**v1.0.1**
- Runtime bug fixes and code cleanup

**v1.0.0**
- Initial release: Combine tab, Library tab, SQLite-backed folder/list storage
