# Block/Allowlist Combiner for Pi-hole

A Python desktop app that fetches, parses, and deduplicates multiple Pi-hole blocklists from URLs, local files, or pasted text — then combines them into a single optimized list ready to push directly to Pi-hole via [phlist-server](https://github.com/appaKappaK/phlist-server).

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
- **COMBINE ALL flash** — button flashes green on success, red on failure, then resets after 2 seconds
- **Push to phlist-server** — push combined lists directly to your phlist-server instance; Push button turns green when the server is verified and output is ready (disabled until connection is tested)
- **Connection polling** — after a manual Test Connection, silently re-checks every 60 seconds so the button auto-updates if the server goes down
- Save combined lists to a local library organized in folders
- Load saved lists back into the combiner to merge with new sources
- **Re-fetch Sources** — re-fetch source URLs for selected lists and rebuild them with fresh data; works with single or multi-select, with a progress bar
- **Combine Selected** — multi-select lists in the Library (Ctrl+click) and merge them into one deduplicated list
- **Refresh Credits** — retroactively extract author credits from source URLs for older saved lists
- **Copy Sources** — one-click copy of all source labels to the clipboard
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
git clone https://github.com/appaKappaK/phlist.git
cd phlist
pip install -e .
```

## Usage

```bash
phlist
```

The app opens with three tabs:

- **Combine** — add sources (URL / file / paste), click *Combine All*, then copy, save, export, or push to your phlist-server
- **Library** — browse saved lists organized in folders, view contents, export, update from sources, or load back into the combiner
- **Settings** — two-column card layout: Remote Server (URL + API key + Test Connection), combine defaults (timeout + filename), library stats, inline log viewer, desktop shortcut installer, and database export/import — all settings persist across restarts

> **Note:** The Blocklist/Allowlist toggle only changes the output header label — it does not affect how Pi-hole processes the list. Blocklists and allowlists should be added on the **Lists** tab in Pi-hole's dashboard.

### Pushing to Pi-hole

This app pairs with [phlist-server](https://github.com/appaKappaK/phlist-server) — a lightweight HTTP server that hosts your combined lists for Pi-hole to pull via gravity.

1. Deploy **phlist-server** on your LAN (see its README for setup)
2. In **Settings → Remote Server**, enter the server URL and API key, then click **Save**
3. Click **Test Connection** — once verified, the app polls the server every 60 seconds for the rest of the session so the status stays current
4. Build your combined list in the **Combine** tab — the **Push** button turns green when the server is reachable and output is ready
5. Click **Push**, enter a slug (e.g. `blocklist`) — the list is uploaded to `{server}/lists/blocklist.txt`
6. Add that URL to Pi-hole's **Lists** tab and run **Update Gravity**

> Pi-hole and your phlist-server just need to be on the same local network.

> **Tip:** To use Pi-hole's group management, build separate lists (e.g. one for general devices, one for smart TVs) and push each with a different slug. Each URL is a separate list entry in Pi-hole that can be assigned to different groups.

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
    settings_tab.py   — Settings tab + connection polling
    tooltip.py        — Hover tooltip widget for buttons and inputs
  combiner.py         — Orchestrates fetch → parse → deduplicate
  updater.py          — Re-fetches sources and re-combines a saved list
  fetcher.py          — Fetches URLs and local files
  parser.py           — Extracts/validates domains from all supported formats
  deduplicator.py     — Tracks unique domains and duplicate count
  database.py         — SQLite library (folders + saved lists + settings)
  remote.py           — Push lists to phlist-server + connection health check
  logger.py           — Rotating log file setup
  _install_desktop.py — Linux desktop shortcut installer
  assets/             — SVG/PNG icons, splash logo, .desktop file
tests/
  test_parser.py
  test_fetcher.py
  test_combiner.py
  test_database.py
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

## What's new in v2.0.2

- **Copy Sources** — new button in the sources panel toolbar to copy all source labels to the clipboard
- **Push requires verified connection** — the Push button is now disabled until Test Connection succeeds; no more accidentally pushing to an unverified server
- **Save to Library stays on Combine tab** — no longer auto-switches to the Library tab after saving
- **API key field Ctrl+A** — the API key entry in Settings now supports Ctrl+A to select all

See [CHANGELOG.md](CHANGELOG.md) for the full version history.
