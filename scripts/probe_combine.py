#!/usr/bin/env python3
"""Probe: ListCombiner parse + dedup logic.

Edit the SAMPLE_LISTS below, then run:
    python scripts/probe_combine.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from piholecombinelist.combiner import ListCombiner

# --- EDIT BELOW ---

SAMPLE_LISTS = [
    # (source_name, raw_content)
    ("list-a", """\
# Comment line
example.com
ads.example.com
0.0.0.0 tracker.net
127.0.0.1 ads.example.com
"""),
    ("list-b", """\
example.com
newsite.org
tracker.net
"""),
]

LIST_TYPE = "Blocklist"

# --- END EDIT ---

if __name__ == "__main__":
    combiner = ListCombiner()
    for name, content in SAMPLE_LISTS:
        added = combiner.add_list(content, name)
        print(f"  [{name}] +{added} new domains")

    stats = combiner.get_stats()
    print(f"\nStats: {stats}")

    result = combiner.get_combined(list_type=LIST_TYPE)
    lines = result.split("\n")
    print(f"\nOutput ({len(lines)} lines):")
    for line in lines[:30]:
        print(f"  {line}")
    if len(lines) > 30:
        print(f"  ... ({len(lines) - 30} more)")
