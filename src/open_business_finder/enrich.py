"""Website contact-channel enrichment (optional, needs `contactchannels`)."""

from __future__ import annotations

import csv
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence

CHANNEL_COLUMNS = (
    "site_ok", "site_error", "channels", "instant_channel", "whatsapp", "telegram", "live_chat",
    "site_emails", "site_phones", "site_socials",
)


_LIST_COLUMNS = ("channels", "whatsapp", "telegram", "live_chat", "site_emails", "site_phones", "site_socials")


class EnrichUnavailable(RuntimeError):
    """The optional contact-channel-detector package is not installed."""


def _detector() -> Any:
    try:
        import contactchannels  # type: ignore
    except ImportError as exc:
        raise EnrichUnavailable(
            'Enrichment needs the optional detector: pip install "open-business-finder[channels]" '
            "(or pip install git+https://github.com/Pinlyx/contact-channel-detector)"
        ) from exc
    return contactchannels


def summarise(result: Any) -> Dict[str, Any]:
    """Flatten a contactchannels Result into the output columns."""
    return {
        "site_ok": bool(result.ok),
        "site_error": result.error or "",
        "channels": list(result.channels),
        "instant_channel": bool(result.instant_channel),
        "whatsapp": result.values("whatsapp"),
        "telegram": result.values("telegram"),
        "live_chat": result.providers("live_chat"),
        "site_emails": result.values("email"),
        "site_phones": result.values("phone"),
        "site_socials": ["%s:%s" % (k, v) for k, v in result.social.items()],
    }


def enrich_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    website_field: str = "website",
    concurrency: int = 8,
    timeout: float = 12.0,
    respect_robots: bool = False,
    progress: Optional[Callable[[int, int], None]] = None,
    detect: Optional[Callable[[str], Any]] = None,
) -> List[Dict[str, Any]]:
    """Return copies of ``rows`` with channel columns added.

    Rows without a website get empty channel columns. ``detect`` replaces the
    network fetch (tests); by default it is ``contactchannels.detect``.
    """
    if detect is None:
        mod = _detector()

        def detect(url: str) -> Any:  # noqa: F811
            return mod.detect(url, timeout=timeout, respect_robots=respect_robots)

    urls = {}
    for row in rows:
        url = (row.get(website_field) or "").strip()
        if url:
            urls.setdefault(url, None)
    total = len(urls)
    done = 0

    def work(url: str) -> Any:
        return summarise(detect(url))

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {url: pool.submit(work, url) for url in urls}
        for url, fut in futures.items():
            try:
                urls[url] = fut.result()
            except Exception as exc:  # a broken site must never abort the batch
                urls[url] = {"site_ok": False, "site_error": "detector error: %s" % exc}
            done += 1
            if progress:
                progress(done, total)

    out: List[Dict[str, Any]] = []
    for row in rows:
        merged = dict(row)
        found = urls.get((row.get(website_field) or "").strip())
        for col in CHANNEL_COLUMNS:
            empty: Any = [] if col in _LIST_COLUMNS else ""
            merged[col] = (found or {}).get(col, empty)
        out.append(merged)
    return out


def read_rows(path: str) -> List[Dict[str, Any]]:
    """Rows from a CSV or JSON (list of objects) file written by `obf search`."""
    if path.lower().endswith(".json"):
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            raise ValueError("expected a JSON list of objects")
        return [dict(r) for r in data]
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return [dict(r) for r in csv.DictReader(fh)]
