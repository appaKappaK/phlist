#!/usr/bin/env python3
"""Probe: updater pipeline (re-fetch + re-combine from sources JSON).

Edit the SOURCES and temp files below, then run:
    python scripts/probe_update.py
"""

import json
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pathlib import Path
from piholecombinelist.updater import has_fetchable_sources, update_list

# --- EDIT BELOW ---

# Set to True to create temp files and test file-based sources
USE_FILE_SOURCES = True

# Raw sources JSON (used if USE_FILE_SOURCES is False)
SOURCES_JSON = '[{"type": "url", "label": "http://localhost:19999/nonexistent"}]'

LIST_TYPE = "Blocklist"

# --- END EDIT ---

if __name__ == "__main__":
    if USE_FILE_SOURCES:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create sample list files
            f1 = Path(tmpdir) / "list1.txt"
            f1.write_text("example.com\nads.com\ntracker.net\n")
            f2 = Path(tmpdir) / "list2.txt"
            f2.write_text("ads.com\nnewsite.org\nmalware.bad\n")

            sources = [
                {"type": "file", "label": str(f1)},
                {"type": "file", "label": str(f2)},
            ]
            sources_json = json.dumps(sources)

            print(f"=== has_fetchable_sources ===")
            print(f"  {has_fetchable_sources(sources_json)}")

            print(f"\n=== update_list ===")
            content, domain_count, dupes, failed = update_list(sources_json, LIST_TYPE)
            print(f"  Domains: {domain_count}")
            print(f"  Duplicates removed: {dupes}")
            print(f"  Failed: {failed}")
            if content:
                lines = content.split("\n")
                print(f"\n  Output ({len(lines)} lines):")
                for line in lines[:20]:
                    print(f"    {line}")
    else:
        print(f"=== has_fetchable_sources ===")
        print(f"  {has_fetchable_sources(SOURCES_JSON)}")

        print(f"\n=== update_list ===")
        content, domain_count, dupes, failed = update_list(SOURCES_JSON, LIST_TYPE)
        print(f"  Domains: {domain_count}")
        print(f"  Duplicates removed: {dupes}")
        print(f"  Failed: {failed}")
