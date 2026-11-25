"""The bundled Overture category list (`obf categories`)."""

from __future__ import annotations

import csv
import difflib
from importlib import resources
from typing import Dict, List, Optional, Sequence

from .text import fold


def load_categories() -> List[Dict[str, object]]:
    """All category names of the bundled snapshot, most common first.

    Each row: category, basic_category, hierarchy (parents joined with ">"),
    places_worldwide (count in the snapshot's Overture release).
    """
    text = resources.files("open_business_finder").joinpath("data/categories.csv").read_text(encoding="utf-8")
    rows: List[Dict[str, object]] = []
    for rec in csv.DictReader(text.splitlines()):
        rows.append({
            "category": rec["category"],
            "basic_category": rec.get("basic_category") or "",
            "hierarchy": rec.get("hierarchy") or "",
            "places_worldwide": int(rec.get("places_worldwide") or 0),
        })
    return rows


def find_categories(query: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, object]]:
    """Categories whose name, basic category or any parent contains ``query``."""
    rows = load_categories()
    if query:
        key = fold(query).replace(" ", "_")
        rows = [
            r for r in rows
            if key in str(r["category"]) or key in str(r["basic_category"]) or key in str(r["hierarchy"]).split(">")
            or any(key in part for part in str(r["hierarchy"]).split(">"))
        ]
    return rows[:limit] if limit else rows


def unknown_categories(cats: Sequence[str]) -> Dict[str, List[str]]:
    """Requested names missing from the bundled snapshot, with close suggestions.

    A name counts as known if it is a category, a basic category or a parent in
    the hierarchy. The snapshot can lag a newer Overture release, so callers
    should only warn, never refuse.
    """
    rows = load_categories()
    known = set()
    for r in rows:
        known.add(str(r["category"]))
        known.add(str(r["basic_category"]))
        known.update(p for p in str(r["hierarchy"]).split(">") if p)
    out: Dict[str, List[str]] = {}
    for cat in cats:
        if cat not in known:
            hits = [str(r["category"]) for r in find_categories(cat, limit=4)]
            if not hits and len(cat) > 4:
                hits = [str(r["category"]) for r in find_categories(cat[:4], limit=4)]
            if not hits:
                hits = difflib.get_close_matches(cat, sorted(known), n=4, cutoff=0.75)
            out[cat] = hits
    return out
