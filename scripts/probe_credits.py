#!/usr/bin/env python3
"""Probe: credit extraction from URLs / surrounding text.

Edit the SAMPLES below, then run:
    python scripts/probe_credits.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from piholecombinelist.gui.combine_tab import _credit_for_url

# --- EDIT BELOW ---

# Each entry is (url, surrounding_line_text)
SAMPLES = [
    # Plain URL — should fall back to GitHub username
    ("https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts",
     "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts"),

    # Markdown table row with label
    ("https://example.com/list.txt",
     "| SomeAuthor | https://example.com/list.txt | enabled |"),

    # YAML config — name on adjacent line (pass as context)
    ("https://adguardteam.github.io/list.txt",
     "- enabled: true url: https://adguardteam.github.io/list.txt name: AdGuard DNS filter"),

    # Long description — should be rejected, fall back to username
    ("https://github.com/Perflyst/PiHoleBlocklist/blob/master/android-tracking.txt",
     "This is a comprehensive list of Android tracking domains maintained by Perflyst"),

    # jsDelivr CDN URL
    ("https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/domains/pro.txt",
     "https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/domains/pro.txt"),

    # codeberg.page URL
    ("https://someuser.codeberg.page/blocklist.txt",
     "https://someuser.codeberg.page/blocklist.txt"),
]

# --- END EDIT ---

if __name__ == "__main__":
    print("=== Credit Extraction ===")
    for url, line in SAMPLES:
        credit = _credit_for_url(url, line)
        print(f"  URL:    {url}")
        print(f"  Line:   {line[:80]}{'...' if len(line) > 80 else ''}")
        print(f"  Credit: {credit}")
        print()
