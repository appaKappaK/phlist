"""Remote server integration: push blocklists to a phlist-server instance."""

import logging
import urllib.error
import urllib.request

_log = logging.getLogger(__name__)


def push_list(base_url: str, api_key: str, slug: str, content: str) -> tuple[bool, str]:
    """PUT *content* to ``{base_url}/lists/{slug}.txt`` with Bearer auth.

    Returns ``(success, message)``.
    """
    url = f"{base_url.rstrip('/')}/lists/{slug}.txt"
    data = content.encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="PUT",
        headers={
            "Content-Type": "text/plain; charset=utf-8",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            _log.info("push_list: PUT %s → %s", url, resp.status)
            return True, f"Pushed to {url}"
    except urllib.error.HTTPError as exc:
        _log.warning("push_list: HTTP %s %s for %s", exc.code, exc.reason, url)
        return False, f"HTTP {exc.code}: {exc.reason}"
    except Exception as exc:
        _log.warning("push_list: %s", exc)
        return False, str(exc)


def check_connection(base_url: str, api_key: str) -> tuple[bool, str]:
    """GET ``{base_url}/health`` and verify a 200 response.

    Returns ``(success, message)``.
    """
    url = f"{base_url.rstrip('/')}/health"
    req = urllib.request.Request(
        url, method="GET",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            _log.info("test_connection: %s → %s", url, resp.status)
            return True, f"Connected  ({resp.status} OK)"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.reason}"
    except Exception as exc:
        return False, str(exc)
