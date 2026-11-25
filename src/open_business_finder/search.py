"""The query layer: businesses from Overture places, filtered by area and category.

Stage design (this matters for speed and memory):

1. Cheap filters run against the parquet first: the bounding box columns
   (``bbox.xmin`` ... ``bbox.ymax``) let DuckDB skip most row groups, and the
   category, confidence, website and phone filters shrink the download further.
   The matching rows land in a local temp table.
2. Only then is the real region polygon applied with ``ST_Within`` on that small
   local table. Running ``ST_Within`` straight over remote parquet does not
   stream and balloons memory.
"""

from __future__ import annotations

import math
import re
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import cache, db, divisions
from .categories import unknown_categories
from .release import places_source, resolve_release
from .text import clean_text

FIELDS = (
    "id", "name", "category", "alt_categories", "confidence", "website", "phone", "email",
    "socials", "address", "locality", "country", "lat", "lon", "source",
)

Bbox = Tuple[float, float, float, float]
_CATEGORY_RE = re.compile(r"^[a-z0-9_]+$")
_EARTH_KM = 6371.0088


class SearchError(ValueError):
    """Invalid search arguments."""


def _normalise_categories(category: Any) -> List[str]:
    if category is None:
        return []
    items = re.split(r"[,;]", category) if isinstance(category, str) else list(category)
    out: List[str] = []
    for raw in items:
        key = re.sub(r"[\s\-]+", "_", str(raw).strip().lower())
        if not key:
            continue
        if not _CATEGORY_RE.match(key):
            raise SearchError("Invalid category %r: use Overture category names such as cafe or beauty_salon" % raw)
        if key not in out:
            out.append(key)
    return out


def parse_bbox(value: Any) -> Bbox:
    """``"minlon,minlat,maxlon,maxlat"`` (or a 4-sequence) -> validated tuple."""
    parts = re.split(r"[,\s]+", value.strip()) if isinstance(value, str) else list(value)
    try:
        x0, y0, x1, y1 = (float(p) for p in parts)
    except (TypeError, ValueError):
        raise SearchError("bbox must be four numbers: minlon,minlat,maxlon,maxlat") from None
    if not (-180 <= x0 <= x1 <= 180 and -90 <= y0 <= y1 <= 90):
        raise SearchError("bbox must satisfy -180 <= minlon <= maxlon <= 180 and -90 <= minlat <= maxlat <= 90")
    return (x0, y0, x1, y1)


def parse_near(value: Any) -> Tuple[float, float]:
    """``"lat,lon"`` (or a 2-sequence) -> (lat, lon)."""
    parts = re.split(r"[,\s]+", value.strip()) if isinstance(value, str) else list(value)
    try:
        lat, lon = (float(p) for p in parts)
    except (TypeError, ValueError):
        raise SearchError("near must be two numbers: lat,lon") from None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise SearchError("near is out of range: lat must be -90..90, lon -180..180")
    return lat, lon


def near_bbox(lat: float, lon: float, radius_km: float) -> Bbox:
    dlat = radius_km / 111.32
    dlon = radius_km / (111.32 * max(math.cos(math.radians(lat)), 0.01))
    return (max(lon - dlon, -180.0), max(lat - dlat, -90.0), min(lon + dlon, 180.0), min(lat + dlat, 90.0))


def _intersect(a: Optional[Bbox], b: Optional[Bbox]) -> Optional[Bbox]:
    if a is None:
        return b
    if b is None:
        return a
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def _area_km2(box: Bbox) -> float:
    mid = math.radians((box[1] + box[3]) / 2)
    return max(box[2] - box[0], 0) * 111.32 * math.cos(mid) * max(box[3] - box[1], 0) * 111.32


class _Heartbeat:
    """Prints a line to stderr every ``every`` seconds while a slow query runs."""

    def __init__(self, label: str, log: Callable[[str], None], every: float = 15.0):
        self.label, self.log, self.every = label, log, every
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._t0 = time.time()

    def _run(self) -> None:
        while not self._stop.wait(self.every):
            self.log("  ... %s, still working (%ds)" % (self.label, int(time.time() - self._t0)))

    def __enter__(self) -> "_Heartbeat":
        self._thread.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._stop.set()


def _columns(con: Any, src: str) -> List[str]:
    rows = con.execute("DESCRIBE SELECT * FROM read_parquet(%s)" % db.sql_literal(src)).fetchall()
    return [r[0] for r in rows]


def _category_sql(columns: Sequence[str], cats: List[str]) -> Tuple[str, List[Any]]:
    """WHERE fragment and params for the category filter.

    Current releases carry ``taxonomy`` (primary plus a parent hierarchy, so
    ``food_and_drink`` style parents work too) and ``basic_category``. Older
    releases only have ``categories``.
    """
    ph = ",".join("?" for _ in cats)
    if "taxonomy" in columns:
        sql = "(taxonomy.\"primary\" IN (%s) OR list_has_any(taxonomy.hierarchy, [%s])" % (ph, ph)
        params: List[Any] = cats + cats
        if "basic_category" in columns:
            sql += " OR basic_category IN (%s)" % ph
            params += cats
        return sql + ")", params
    if "categories" in columns:
        return "(categories.\"primary\" IN (%s) OR list_has_any(categories.alternate, [%s]))" % (ph, ph), cats + cats
    raise SearchError("This places source has neither a taxonomy nor a categories column")


def _category_select(columns: Sequence[str]) -> Tuple[str, str]:
    if "taxonomy" in columns:
        return "taxonomy.\"primary\"", "taxonomy.alternates"
    if "categories" in columns:
        return "categories.\"primary\"", "categories.alternate"
    return "NULL::VARCHAR", "NULL::VARCHAR[]"


def _row_to_place(row: Sequence[Any], release_label: str, with_distance: bool) -> Dict[str, Any]:
    (pid, name, cat, alts, conf, website, phone, email, socials, free, locality, postcode,
     region, country, lat, lon) = row[:16]
    free_c, loc_c, post_c = clean_text(free), clean_text(locality), clean_text(postcode)
    parts = [p for p in (free_c,) if p]
    tail = " ".join(p for p in (post_c, loc_c) if p and (not free_c or p not in free_c))
    if tail:
        parts.append(tail)
    place: Dict[str, Any] = {
        "id": str(pid),
        "name": clean_text(name),
        "category": clean_text(cat),
        "alt_categories": [c for c in (clean_text(a) for a in (alts or [])) if c],
        "confidence": round(conf, 3) if conf is not None else None,
        "website": clean_text(website),
        "phone": clean_text(phone),
        "email": clean_text(email),
        "socials": [s for s in (clean_text(x) for x in (socials or [])) if s],
        "address": ", ".join(parts) or None,
        "locality": loc_c,
        "country": clean_text(country),
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "source": release_label,
    }
    if with_distance:
        place["distance_km"] = round(row[16], 3)
    return place


def search(
    country: Optional[str] = None,
    region: Optional[str] = None,
    county: Optional[str] = None,
    category: Any = None,
    near: Any = None,
    radius_km: float = 1.0,
    bbox: Any = None,
    has_website: bool = False,
    has_phone: bool = False,
    min_confidence: Optional[float] = None,
    limit: Optional[int] = 500,
    release: Optional[str] = None,
    *,
    places_path: Optional[str] = None,
    divisions_path: Optional[str] = None,
    cache_results: bool = True,
    progress: Optional[Callable[[str], None]] = None,
) -> List[Dict[str, Any]]:
    """Local businesses from Overture Maps places, as a list of dicts.

    Scope with at least one of: ``region``/``county`` (needs ``country``),
    ``bbox`` ("minlon,minlat,maxlon,maxlat"), ``near`` ("lat,lon" plus
    ``radius_km``), or ``country`` alone (slow: whole country).

    ``places_path`` / ``divisions_path`` replace the remote Overture parquet
    with local files (tests, offline mirrors). Results from remote data are
    cached; local sources are never cached.
    """
    log = progress or (lambda _m: None)
    cats = _normalise_categories(category)
    for bad, hints in unknown_categories(cats).items():
        log("Warning: %r is not a known Overture category%s. See `obf categories`." % (
            bad, " (did you mean: %s?)" % ", ".join(hints) if hints else ""))
    country_c = country.strip().upper() if country else None
    if (region or county) and not country_c:
        raise SearchError("--country is required with --region or --county")
    if not (region or county or bbox or near or country_c):
        raise SearchError("Give a scope: --country (with --region/--county), --bbox or --near")
    user_box = parse_bbox(bbox) if bbox else None
    near_pt = parse_near(near) if near else None
    if near_pt and radius_km <= 0:
        raise SearchError("radius_km must be positive")
    if min_confidence is not None and not 0 <= float(min_confidence) <= 1:
        raise SearchError("min_confidence must be between 0 and 1")
    if limit is not None and limit < 0:
        raise SearchError("limit must be 0 or positive")

    need_polygon = bool(region or county)
    needs_release = places_path is None or (need_polygon and divisions_path is None)
    rel = resolve_release(release) if needs_release else (release or "local")
    src = places_path or places_source(rel)
    remote = db.is_remote(src)

    key = None
    if cache_results and remote and divisions_path is None:
        key = cache.result_key({
            "v": 1, "release": rel, "country": country_c, "region": region, "county": county, "cats": cats,
            "near": near_pt, "radius": radius_km if near_pt else None, "bbox": user_box, "web": has_website,
            "phone": has_phone, "conf": min_confidence, "limit": limit,
        })
        hit = cache.load_result(key)
        if hit is not None:
            log("Using cached result (%d rows). Pass --no-cache to query again." % len(hit))
            return hit

    started = time.time()
    div_remote = need_polygon and (divisions_path is None or db.is_remote(divisions_path))
    con = db.connect(remote=remote or div_remote, spatial=need_polygon)
    try:
        area_box: Optional[Bbox] = None
        polygon_ids: List[str] = []
        div_table: Optional[str] = None
        if need_polygon:
            log("Resolving area %s ..." % " / ".join(x for x in (country_c, region, county) if x))
            div_table, matches = divisions.resolve(
                con, country_c or "", region=region, county=county, release=rel,
                source=divisions_path, use_cache=cache_results and divisions_path is None, log=log,
            )
            polygon_ids = [i for d in matches for i in d.id.split(",")]
            area_box = (
                min(d.bbox[0] for d in matches), min(d.bbox[1] for d in matches),
                max(d.bbox[2] for d in matches), max(d.bbox[3] for d in matches),
            )
            log("Area: %s (%d polygon%s)" % (", ".join(sorted({d.name for d in matches})), len(polygon_ids),
                                             "" if len(polygon_ids) == 1 else "s"))

        box = _intersect(_intersect(area_box, user_box), near_bbox(*near_pt, radius_km) if near_pt else None)
        if box is not None and (box[0] > box[2] or box[1] > box[3]):
            return []

        columns = _columns(con, src)
        cat_primary, cat_alt = _category_select(columns)

        where: List[str] = ['names."primary" IS NOT NULL', "(operating_status IS NULL OR operating_status <> 'closed')"]
        params: List[Any] = []
        if box is not None:
            where.append("bbox.xmin BETWEEN ? AND ? AND bbox.ymin BETWEEN ? AND ?")
            params += [box[0], box[2], box[1], box[3]]
        elif country_c:
            where.append("addresses[1].country = ?")
            params.append(country_c)
        if cats:
            frag, cparams = _category_sql(columns, cats)
            where.append(frag)
            params += cparams
        if min_confidence is not None:
            where.append("confidence >= ?")
            params.append(float(min_confidence))
        if has_website:
            where.append("len(websites) > 0")
        if has_phone:
            where.append("len(phones) > 0")

        dist_sql = "NULL::DOUBLE"
        select_params: List[Any] = []
        if near_pt:
            dist_sql = ("2 * %r * asin(sqrt(pow(sin(radians(bbox.ymin - ?) / 2), 2) + cos(radians(?)) * "
                        "cos(radians(bbox.ymin)) * pow(sin(radians(bbox.xmin - ?) / 2), 2)))" % _EARTH_KM)
            select_params = [near_pt[0], near_pt[0], near_pt[1]]
            where.append(dist_sql + " <= ?")
            params += select_params + [radius_km]

        select = (
            "SELECT id, names.\"primary\" AS name, %s AS category, %s AS alts, confidence, websites[1] AS website, "
            "phones[1] AS phone, emails[1] AS email, socials, addresses[1].freeform AS freeform, "
            "addresses[1].locality AS locality, addresses[1].postcode AS postcode, addresses[1].region AS region, "
            "addresses[1].country AS country, bbox.ymin AS lat, bbox.xmin AS lon, %s AS dist"
            % (cat_primary, cat_alt, dist_sql)
        )
        where_sql = " AND ".join(where)
        order = ("dist ASC, " if near_pt else "") + "confidence DESC NULLS LAST, name ASC"
        limit_sql = " LIMIT %d" % limit if limit else ""
        from_sql = "FROM read_parquet(%s)" % db.sql_literal(src)

        if box is not None:
            log("Querying places in a %.1f km2 bounding box%s. %s" % (
                _area_km2(box), " from Overture (remote)" if remote else "",
                "Small areas take seconds; whole cities or regions can take minutes." if remote else ""))
        else:
            log("Querying places for the whole country; this is slow. Narrow it with --region or --bbox.")

        # Placeholders appear in text order: SELECT (distance), then WHERE.
        if not need_polygon:
            sql = "%s %s WHERE %s ORDER BY %s%s" % (select, from_sql, where_sql, order, limit_sql)
            with _Heartbeat("downloading matching places", log):
                rows = con.execute(sql, select_params + params).fetchall()
        else:
            with _Heartbeat("downloading candidate places", log):
                con.execute("CREATE TEMP TABLE cand AS %s %s WHERE %s" % (select, from_sql, where_sql),
                            select_params + params)
            n_cand = con.execute("SELECT count(*) FROM cand").fetchone()[0]
            log("%d candidates in the bounding box; keeping those inside the polygon ..." % n_cand)
            id_ph = ",".join("?" for _ in polygon_ids)
            sql = (
                "WITH area AS (SELECT ST_Union_Agg(ST_GeomFromWKB(wkb)) AS g FROM %s WHERE id IN (%s)) "
                "SELECT cand.* FROM cand, area WHERE ST_Within(ST_Point(cand.lon, cand.lat), area.g) "
                "ORDER BY %s%s" % (div_table, id_ph, order, limit_sql)
            )
            with _Heartbeat("testing points against the polygon", log):
                rows = con.execute(sql, polygon_ids).fetchall()

        label = "overture:%s" % rel
        places = [_row_to_place(r, label, near_pt is not None) for r in rows]
        places = [p for p in places if p["name"]]
        log("%d places in %.1fs" % (len(places), time.time() - started))
        if key is not None:
            cache.save_result(key, places)
        return places
    finally:
        con.close()


def stderr_log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)
