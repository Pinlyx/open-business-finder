"""CSV, JSON and GeoJSON writers."""

from __future__ import annotations

import csv
import io
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence, TextIO

from .search import FIELDS

FORMATS = ("csv", "json", "geojson")
_LIST_SEP = {"alt_categories": ";", "socials": " | "}


def infer_format(fmt: Optional[str], out: Optional[str]) -> str:
    """Explicit format wins; else the file extension; else csv."""
    if fmt:
        return fmt
    if out:
        ext = os.path.splitext(out)[1].lower()
        if ext == ".json":
            return "json"
        if ext in (".geojson", ".geo.json"):
            return "geojson"
    return "csv"


def columns_for(rows: Sequence[Dict[str, Any]], base: Sequence[str] = FIELDS) -> List[str]:
    """Known fields first (in their documented order), then any extra keys."""
    seen: List[str] = [c for c in base if any(c in r for r in rows)] if rows else list(base)
    for row in rows:
        for key in row:
            if key not in seen:
                seen.append(key)
    return seen


def _flat(value: Any, key: str) -> Any:
    if isinstance(value, (list, tuple)):
        return _LIST_SEP.get(key, ";").join(str(v) for v in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else value


def write_csv(rows: Sequence[Dict[str, Any]], fp: TextIO, columns: Optional[Sequence[str]] = None) -> None:
    cols = list(columns) if columns else columns_for(rows)
    writer = csv.writer(fp, lineterminator="\n")
    writer.writerow(cols)
    for row in rows:
        writer.writerow([_flat(row.get(c), c) for c in cols])


def write_json(rows: Sequence[Dict[str, Any]], fp: TextIO) -> None:
    json.dump(list(rows), fp, ensure_ascii=False, indent=2)
    fp.write("\n")


def to_geojson(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    features = []
    for row in rows:
        lat, lon = row.get("lat"), row.get("lon")
        if lat is None or lon is None:
            continue
        props = {k: v for k, v in row.items() if k not in ("lat", "lon")}
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })
    return {"type": "FeatureCollection", "features": features}


def write_geojson(rows: Sequence[Dict[str, Any]], fp: TextIO) -> None:
    json.dump(to_geojson(rows), fp, ensure_ascii=False)
    fp.write("\n")


def write(rows: Sequence[Dict[str, Any]], fmt: str, fp: TextIO) -> None:
    if fmt == "csv":
        write_csv(rows, fp)
    elif fmt == "json":
        write_json(rows, fp)
    elif fmt == "geojson":
        write_geojson(rows, fp)
    else:
        raise ValueError("unknown format %r (use one of: %s)" % (fmt, ", ".join(FORMATS)))


def render(rows: Sequence[Dict[str, Any]], fmt: str) -> str:
    buf = io.StringIO()
    write(rows, fmt, buf)
    return buf.getvalue()


def write_file(rows: Sequence[Dict[str, Any]], fmt: str, path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        write(rows, fmt, fh)
