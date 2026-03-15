# Pi-hole Combined Blocklist Generator

A Python desktop app that fetches, parses, and deduplicates multiple Pi-hole blocklists from URLs, local files, or pasted text — then combines them into a single optimized list.

## Features

- Fetch blocklists from URLs or local `.txt` files
- Paste raw blocklist text directly into the app
- Parses all common formats: plain domains, `0.0.0.0 domain`, `127.0.0.1 domain`
- Deduplicates across all sources and reports how many duplicates were removed
- Saves combined lists to a local library organized in folders
- Load saved lists back into the combiner to merge with new sources
- Dark mode desktop GUI (customtkinter)

## Installation

```bash
git clone https://github.com/yourusername/PiHoleCombineList.git
cd PiHoleCombineList
pip install -e .
```

## Usage

```bash
pihole-gui
```

The app opens with two tabs:

- **Combine** — add sources (URL / file / paste), click *Combine All*, then copy, save, or push to the library
- **Library** — browse saved lists organized in folders, view contents, export, or load back into the combiner

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
