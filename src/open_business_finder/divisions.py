"""Administrative areas (regions, counties, ...) from the Overture divisions theme.

Two traps this module handles on purpose:

* Coastal regions come twice in ``division_area``: once as ``class = 'land'`` and
  once as ``class = 'maritime'`` (territorial waters). Only land is wanted.
* The address ``region`` field on places is empty for most places in many
  countries, so filtering places by that text is unreliable. Areas are therefore
  resolved to polygons and places are tested geometrically.

Areas are downloaded once per (release, country, level) and cached as a small
parquet file under the cache directory.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import cache, db
from .text import clean_text, fold

LEVELS = ("region", "county", "localadmin", "locality", "neighborhood")

Bbox = Tuple[float, float, float, float]  # minlon, minlat, maxlon, maxlat


class AreaError(ValueError):
    """The requested area is unknown or ambiguous."""


@dataclass(frozen=True)
class Division:
    id: str
    name: str
    level: str
    code: Optional[str]  # ISO 3166-2 code of the region this area sits in (e.g. TR-34)
    alt_names: Tuple[str, ...]
    bbox: Bbox

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "level": self.level,
            "code": self.code,
            "bbox": list(self.bbox),
        }

    def keys(self) -> List[str]:
        return [fold(n) for n in (self.name,) + self.alt_names if n]


def _normalise_country(country: str) -> str:
    code = (country or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", code):
        raise AreaError("country must be a 2-letter ISO 3166-1 code such as TR, DE or US, got %r" % country)
    return code


def _check_level(level: str) -> str:
    if level not in LEVELS:
        raise AreaError("level must be one of: %s" % ", ".join(LEVELS))
    return level


def _cache_file(release: str, country: str, level: str):
    return cache.subdir("divisions") / ("%s_%s_%s.parquet" % (release, country, level))


_SELECT = """
SELECT id,
       subtype AS level,
       region AS code,
       names."primary" AS name,
       coalesce(map_values(names.common), []::VARCHAR[]) AS alts,
       bbox.xmin AS xmin, bbox.ymin AS ymin, bbox.xmax AS xmax, bbox.ymax AS ymax,
       ST_AsWKB(geometry) AS wkb
FROM read_parquet({src})
WHERE country = ? AND subtype = ? AND class = 'land' AND names."primary" IS NOT NULL
"""


def load(
    con: Any,
    country: str,
    level: str,
    *,
    release: str,
    source: Optional[str] = None,
    use_cache: bool = True,
    log: Callable[[str], None] = lambda _m: None,
) -> str:
    """Materialise the areas of one level as a DuckDB temp table; returns its name.

    ``source`` overrides the remote divisions parquet (used by the tests); a
    custom source is never cached. The connection must have spatial loaded.
    """
    from .release import divisions_source

    country = _normalise_country(country)
    _check_level(level)
    table = "divs_%s_%s" % (country.lower(), level)
    existing = [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()]
    if table in existing:
        return table

    src = source or divisions_source(release)
    cached = _cache_file(release, country, level) if (use_cache and source is None) else None
    if cached is not None and cached.exists():
        con.execute("CREATE TEMP TABLE %s AS SELECT * FROM read_parquet(%s)" % (table, db.sql_literal(str(cached))))
        return table

    if db.is_remote(src):
        log("Downloading %s %s boundaries (once, then cached; can take a minute or more)" % (country, level))
    con.execute(
        "CREATE TEMP TABLE %s AS %s" % (table, _SELECT.format(src=db.sql_literal(src))),
        [country, level],
    )
    if cached is not None:
        tmp = cached.with_suffix(".tmp")
        con.execute("COPY %s TO %s (FORMAT parquet)" % (table, db.sql_literal(str(tmp))))
        tmp.replace(cached)
    return table


def divisions(con: Any, table: str) -> List[Division]:
    """Rows of a loaded areas table, sorted by name, duplicates merged by (name, code)."""
    rows = con.execute(
        "SELECT id, level, code, name, alts, xmin, ymin, xmax, ymax FROM %s ORDER BY name, code, id" % table
    ).fetchall()
    merged: Dict[Tuple[str, Optional[str]], Division] = {}
    for rid, level, code, name, alts, x0, y0, x1, y1 in rows:
        name_c = clean_text(name) or ""
        key = (name_c, code)
        alt = tuple(a for a in (clean_text(a) for a in (alts or [])) if a)
        if key in merged:
            prev = merged[key]
            box = (min(prev.bbox[0], x0), min(prev.bbox[1], y0), max(prev.bbox[2], x1), max(prev.bbox[3], y1))
            merged[key] = Division(prev.id + "," + str(rid), name_c, level, code, prev.alt_names, box)
        else:
            merged[key] = Division(str(rid), name_c, level, code, alt, (x0, y0, x1, y1))
    return list(merged.values())


def find(items: Sequence[Division], query: str, what: str = "area") -> List[Division]:
    """Items whose name or translated name matches ``query`` (accent/case insensitive).

    Exact folded matches win; otherwise prefix matches are accepted.
    Raises AreaError with suggestions when nothing matches.
    """
    key = fold(query)
    exact = [d for d in items if key in d.keys()]
    if exact:
        return exact
    prefix = [d for d in items if any(k.startswith(key) for k in d.keys())]
    if prefix:
        return prefix
    names = sorted({d.name for d in items})
    close = difflib.get_close_matches(query, names, n=5, cutoff=0.5)
    hint = " Did you mean: %s?" % ", ".join(close) if close else ""
    raise AreaError("No %s named %r found.%s List them with `obf regions`." % (what, query, hint))


def resolve(
    con: Any,
    country: str,
    *,
    region: Optional[str] = None,
    county: Optional[str] = None,
    release: str,
    source: Optional[str] = None,
    use_cache: bool = True,
    log: Callable[[str], None] = lambda _m: None,
) -> Tuple[str, List[Division]]:
    """Resolve ``--region`` / ``--county`` to one area.

    Returns (temp table name, matching rows). The rows of the table whose ids
    are in the returned divisions define the polygon to test places against.
    """
    kw = dict(release=release, source=source, use_cache=use_cache, log=log)
    parent_code: Optional[str] = None
    if region:
        rtable = load(con, country, "region", **kw)
        matches = find(divisions(con, rtable), region, "region")
        codes = {d.code for d in matches}
        if len(codes) > 1:
            raise AreaError(
                "Region %r is ambiguous: %s" % (region, ", ".join(sorted("%s (%s)" % (d.name, d.code) for d in matches)))
            )
        if not county:
            return rtable, matches
        parent_code = matches[0].code
    if county:
        ctable = load(con, country, "county", **kw)
        items = divisions(con, ctable)
        if parent_code:
            items = [d for d in items if d.code == parent_code]
            if not items:
                raise AreaError("No counties are recorded under region %r for this country." % region)
        matches = find(items, county, "county")
        codes = {d.code for d in matches}
        if len(codes) > 1:
            raise AreaError(
                "County %r exists in several regions (%s). Add --region to choose."
                % (county, ", ".join(sorted(str(c) for c in codes)))
            )
        return ctable, matches
    raise AreaError("Give a region or a county")


def list_areas(
    country: str,
    level: str = "region",
    parent: Optional[str] = None,
    *,
    release: Optional[str] = None,
    source: Optional[str] = None,
    use_cache: bool = True,
    log: Callable[[str], None] = lambda _m: None,
) -> List[Dict[str, Any]]:
    """Names and ids of the areas of one level (the data behind `obf regions`)."""
    from .release import resolve_release

    country = _normalise_country(country)
    _check_level(level)
    rel = resolve_release(release) if source is None else (release or "local")
    con = db.connect(remote=bool(source is None or db.is_remote(source)), spatial=True)
    try:
        kw = dict(release=rel, source=source, use_cache=use_cache, log=log)
        items = divisions(con, load(con, country, level, **kw))
        if parent:
            if level == "region":
                raise AreaError("--parent needs a level below region (county, localadmin, locality, neighborhood)")
            regions = find(divisions(con, load(con, country, "region", **kw)), parent, "region")
            codes = {d.code for d in regions}
            items = [d for d in items if d.code in codes]
        return [d.to_dict() for d in items]
    finally:
        con.close()
