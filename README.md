# Block/Allowlist Combiner for Pi-hole

A Python desktop app that fetches, parses, and deduplicates multiple Pi-hole blocklists from URLs, local files, or pasted text — then combines them into a single optimized list ready to push directly to Pi-hole.

> **Note:** Releases may not reflect the latest changes. Clone the repo for the newest features.

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
- **Re-fetch Sources** — re-fetch source URLs for selected lists and rebuild them with fresh data; works with single or multi-select, with a progress bar; auto-refreshes hosted content
- **Combine Selected** — multi-select lists in the Library (Ctrl+click) and merge them into one deduplicated list
- **Refresh Credits** — retroactively extract author credits from source URLs for older saved lists
- **Fetch cache** — re-combining after adding a few new sources skips re-downloading previously fetched URLs
- **Source dedup** — duplicate URLs are blocked on add; sources display sorted alphabetically
- **Splash screen** — branded loading screen with app logo while the GUI initializes
- **Logging** — rotating log file at `~/.local/share/phlist/phlist.log` for debugging
- **Export / Import database** — back up your entire library to a `.db` file and restore it on any machine
- **Security hardening** — 50 MB response cap, null-byte stripping, SSRF redirect protection, and unicode bidi-override sanitization on saved names
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
- **Library** — browse saved lists organized in folders, view contents, export, update from sources, or load back into the combiner
- **Settings** — two-column card layout: appearance (Light/Dark/System), server port, list type toggle, combine defaults (timeout + filename), library stats, inline log viewer, desktop shortcut installer, and database export/import — all settings persist across restarts

> **Note:** The Blocklist/Allowlist toggle only changes the output header label — it does not affect how Pi-hole processes the list. Blocklists and allowlists should be added on the **Lists** tab in Pi-hole's dashboard.

### Pushing to Pi-hole

1. Build your combined list in the Combine tab
2. Optionally type a filename (e.g. `general`) — leave blank for the default `blocklist.txt`
3. Click **Host List** — the `●` indicator turns green and a URL appears (e.g. `http://YOUR.IP.GO.HERE:8765/general.txt`)
4. Copy the URL and add it on Pi-hole's **Lists** tab
5. Run **Update Gravity** in Pi-hole — it fetches and caches the list
6. Click **Stop Hosting** or close the app — Pi-hole retains the list from its gravity cache

> Pi-hole and your PC just need to be on the same local network. The server defaults to port **8765**.

> **Tip:** To use Pi-hole's group management, build separate lists (e.g. one for general devices, one for smart TVs) and host each with a different filename. Each URL is a separate list entry in Pi-hole that can be assigned to different groups.

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
src/phlist/
  gui/
    app.py            — Main window, tab wiring, splash screen
    combine_tab.py    — Combine tab + URL/credit extraction + fetch cache
    library_tab.py    — Library tab + multi-select + combine selected
    settings_tab.py   — Settings tab
    tooltip.py        — Hover tooltip widget for buttons and inputs
  combiner.py         — Orchestrates fetch → parse → deduplicate
  updater.py          — Re-fetches sources and re-combines a saved list
  fetcher.py          — Fetches URLs and local files
  parser.py           — Extracts/validates domains from all supported formats
  deduplicator.py     — Tracks unique domains and duplicate count
  database.py         — SQLite library (folders + saved lists + settings)
  server.py           — LAN HTTP server for Pi-hole gravity integration
  logger.py           — Rotating log file setup
  _install_desktop.py — Linux desktop shortcut installer
  assets/             — SVG/PNG icons, splash logo, .desktop file
tests/
  test_parser.py
  test_fetcher.py
  test_combiner.py
  test_database.py
  test_server.py
  test_updater.py
  test_stress.py
scripts/
  probe_combine.py    — Dev: poke at combiner parse + dedup
  probe_fetch.py      — Dev: poke at fetch + URL normalization
  probe_credits.py    — Dev: poke at credit extraction
  probe_db.py         — Dev: poke at DB operations
  probe_update.py     — Dev: poke at update pipeline
  agent/
    gen_assets.py     — Regenerate all derived image assets from SVG
    render_svg.py     — SVG → PNG renderer (cairosvg / rsvg / ImageMagick)
    resize_png.py     — PNG resizer (Pillow / ImageMagick)
    image_info.py     — Image metadata printer
```

## Data storage

| Path | Contents | Created by |
|------|----------|------------|
| `~/.local/share/phlist/phlist.db` | Library (folders, saved lists, settings) | App on first launch |
| `~/.local/share/phlist/phlist.log` | Rotating debug log (1 MB, 1 backup) | App on first launch |
| `~/.local/share/applications/phlist.desktop` | Launcher entry | `phlist-desktop` / Settings tab |
| `~/.local/share/icons/hicolor/scalable/apps/phlist.svg` | SVG icon | `phlist-desktop` / Settings tab |
| `~/.local/share/icons/hicolor/256x256/apps/phlist.png` | PNG icon | `phlist-desktop` / Settings tab |

The desktop shortcut files are only created if you run the desktop installer — the app itself only writes the database and log file.

## Running tests

```bash
pytest tests/
```

## Requirements

- Python 3.9+
- `requests`
- `customtkinter`
- `Pillow` (splash screen logo)
- SQLite (Python stdlib)
- `http.server` / `socket` (Python stdlib — no extra install needed for Host List)

## What's new in v1.8.3

- **Settings tab overhaul** — two-column card layout with visible section borders, library stats panel, inline log viewer, fetch timeout and default filename settings, appearance toggle (Light/Dark/System)
- **Export / Import database** — back up and restore your entire library as a `.db` file from the Settings tab; import applies live without a restart
- **Open Data Folder** — one-click access to `~/.local/share/phlist/` from Settings
- **Security hardening** — 50 MB response size cap, null-byte stripping from fetched content, SSRF protection (redirects to private IPs are rejected), unicode bidi-override and zero-width character sanitization on all saved names
- **Test suite expanded** — 106 → 123 tests covering previously untested paths and all new security behaviour
- **Package renamed** `piholecombinelist` → `phlist` — consistent with the CLI command; data directory and database migrate automatically on first launch

See [CHANGELOG.md](CHANGELOG.md) for the full version history.
