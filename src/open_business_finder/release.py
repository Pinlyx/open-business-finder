"""Overture release discovery and source paths."""

from __future__ import annotations

import re
import urllib.request
from typing import Optional

from . import cache

#: Fallback when the live release list cannot be read.
DEFAULT_RELEASE = "2026-11-18.0"

BUCKET = "overturemaps-us-west-2"
S3_REGION = "us-west-2"
_LIST_URL = "https://%s.s3.amazonaws.com/?list-type=2&prefix=release/&delimiter=/" % BUCKET
_RELEASE_RE = re.compile(r"<Prefix>release/(\d{4}-\d{2}-\d{2}\.\d+)/</Prefix>")
_DAY = 24 * 3600


def _sort_key(release: str):
    date, _, rev = release.partition(".")
    return (date, int(rev or 0))


def latest_release(timeout: float = 8.0) -> str:
    """Newest release in the public bucket; falls back to a pinned release.

    The answer is cached for a day. If the bucket cannot be listed (offline,
    blocked), the last cached answer is used, then DEFAULT_RELEASE.
    """
    fresh = cache.read_json("latest_release.json", max_age=_DAY)
    if isinstance(fresh, dict) and fresh.get("release"):
        return str(fresh["release"])
    try:
        req = urllib.request.Request(_LIST_URL, headers={"User-Agent": "open-business-finder"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310: fixed https URL
            body = resp.read().decode("utf-8", "replace")
        found = _RELEASE_RE.findall(body)
        if found:
            newest = max(found, key=_sort_key)
            cache.write_json("latest_release.json", {"release": newest})
            return newest
    except Exception:
        pass
    stale = cache.read_json("latest_release.json")
    if isinstance(stale, dict) and stale.get("release"):
        return str(stale["release"])
    return DEFAULT_RELEASE


def resolve_release(release: Optional[str]) -> str:
    """``None``/``"latest"`` -> newest release; anything else is used as given."""
    if release is None or release.strip().lower() in ("", "latest"):
        return latest_release()
    return release.strip()


def places_source(release: str) -> str:
    return "s3://%s/release/%s/theme=places/type=place/*" % (BUCKET, release)


def divisions_source(release: str) -> str:
    return "s3://%s/release/%s/theme=divisions/type=division_area/*" % (BUCKET, release)
