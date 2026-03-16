# Pi-hole Combined Blocklist Generator

A Python desktop app that fetches, parses, and deduplicates multiple Pi-hole blocklists from URLs, local files, or pasted text — then combines them into a single optimized list ready to push directly to Pi-hole.

## Features

- Fetch blocklists from URLs or local `.txt` files
- Paste raw blocklist text directly into the app
- **Extract URLs** from pasted Pi-hole dashboard text (paste your Adlists page, pull the URLs automatically)
- Parses all common blocklist formats:
  - Plain domains: `example.com`
  - Hosts-file: `0.0.0.0 example.com` / `127.0.0.1 example.com`
  - ABP/AdGuard: `||example.com^` (with optional options or path)
  - Pipe-delimited: `example.com | comment`
- Deduplicates across all sources — shows unique domain count and duplicates removed
- Progress bar and per-source status during combine
- Save combined lists to a local library organized in folders
- Load saved lists back into the combiner to merge with new sources
- **Serve List** — hosts the combined list over HTTP on your LAN so Pi-hole can pull it directly via gravity
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

The app opens with two tabs:

- **Combine** — add sources (URL / file / paste), click *Combine All*, then copy, save, export, or push to Pi-hole
- **Library** — browse saved lists organized in folders, view contents, export, or load back into the combiner

### Pushing to Pi-hole

1. Build your combined list in the Combine tab
2. Click **Serve List** — the `●` indicator turns green and a URL appears (e.g. `http://192.168.1.50:8765/blocklist.txt`)
3. Copy the URL and paste it into Pi-hole's **Adlists** page
4. Run **Update Gravity** in Pi-hole — it fetches and caches the list
5. Click **Stop Serving** or close the app — Pi-hole retains the list from its gravity cache

> Pi-hole and your PC just need to be on the same local network. The server defaults to port **8765**.

### Desktop shortcut (Linux)

Click **Install Desktop Shortcut** in the app footer, or run:

```bash
phlist-desktop
```

This installs the icon and `.desktop` entry so the app appears in your GNOME/KDE launcher.

## Project structure

```
src/piholecombinelist/
  gui.py              — Desktop GUI (customtkinter, two tabs)
  combiner.py         — Orchestrates fetch → parse → deduplicate
  fetcher.py          — Fetches URLs and local files
  parser.py           — Extracts/validates domains from all supported formats
  deduplicator.py     — Tracks unique domains and duplicate count
  database.py         — SQLite library (folders + saved lists)
  server.py           — LAN HTTP server for Pi-hole gravity integration
  _install_desktop.py — Linux desktop shortcut installer
  assets/             — SVG/PNG icon, .desktop file
tests/
  test_parser.py
  test_fetcher.py
  test_combiner.py
  test_database.py
```

## Data storage

The library database is stored at:

```
~/.db/piholecombinelist.db
```

## Running tests

```bash
pytest tests/
```

## Requirements

- Python 3.9+
- `requests`
- `customtkinter`
- SQLite (Python stdlib)
- `http.server` / `socket` (Python stdlib — no extra install needed for Serve List)

## Recent updates

**v1.4.1**
- Red/green `●` indicator next to Serve List button shows server state at a glance

**v1.4.0**
- **Serve List** — built-in LAN HTTP server serves the combined list so Pi-hole can pull it via gravity; stops cleanly on app close

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
