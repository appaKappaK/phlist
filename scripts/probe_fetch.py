#!/usr/bin/env python3
"""Probe: ListFetcher URL normalization + optional live fetch.

Edit the URLS and TEST_FETCH below, then run:
    python scripts/probe_fetch.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from piholecombinelist.fetcher import ListFetcher

# --- EDIT BELOW ---

# URLs to test normalization (GitHub blob → raw conversion, etc.)
URLS = [
    "https://github.com/Perflyst/PiHoleBlocklist/blob/master/android-tracking.txt",
    "https://github.com/user/repo/blob/main/lists/ads.txt",
    "https://raw.githubusercontent.com/user/repo/refs/heads/main/list.txt",
    "https://example.com/blocklist.txt",
]

# Set to a real URL to test an actual fetch (or None to skip)
TEST_FETCH = None
# TEST_FETCH = "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts"

# --- END EDIT ---

if __name__ == "__main__":
    print("=== URL Normalization ===")
    for url in URLS:
        normalized = ListFetcher._normalize_url(url)
        changed = " (converted)" if normalized != url else ""
        print(f"  {url}")
        print(f"    -> {normalized}{changed}")
        print()

    if TEST_FETCH:
        print("=== Live Fetch ===")
        fetcher = ListFetcher(timeout=10)
        result = fetcher.fetch(TEST_FETCH)
        if result:
            lines = result.splitlines()
            print(f"  Fetched {len(result)} bytes, {len(lines)} lines")
            for line in lines[:10]:
                print(f"    {line}")
            if len(lines) > 10:
                print(f"    ... ({len(lines) - 10} more)")
        else:
            print("  Fetch failed!")
        print(f"  Stats: {fetcher.get_stats()}")
