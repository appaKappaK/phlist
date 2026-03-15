"""Parse individual lines from blocklist files into clean domain entries."""
# v1.0.0

import re
from typing import Optional

# Matches a valid domain: labels separated by dots, each label alphanumeric + hyphens
_DOMAIN_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
)

# IP prefixes used in hosts-file style blocklists
_IP_PREFIXES = ("0.0.0.0 ", "127.0.0.1 ")


class ListParser:
    """Extract and validate domain names from blocklist lines."""

    def parse_line(self, line: str) -> Optional[str]:
        """
        Extract a domain from a single blocklist line.

        Returns the domain string if valid, None if the line should be skipped.
        """
        line = line.strip()

        # Skip empty lines and comment/marker lines
        if not line or line[0] in ("#", "!", "["):
            return None

        # Strip IP prefix (hosts-file format)
        for prefix in _IP_PREFIXES:
            if line.startswith(prefix):
                line = line[len(prefix):]
                break

        # Strip inline comment
        if "#" in line:
            line = line.split("#", 1)[0].strip()

        if not line:
            return None

        domain = line.lower()

        if not _DOMAIN_RE.match(domain):
            return None

        return domain
