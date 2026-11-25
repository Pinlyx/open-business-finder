"""Command line: ``obf`` / ``open-business-finder``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Sequence

from . import __version__, divisions, enrich, output
from .categories import find_categories
from .db import DependencyError
from .search import SearchError, search, stderr_log


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="obf",
        description="Find local businesses in any country from open map data (Overture Maps). "
                    "No API key, no browser, no scraping of Google.",
    )
    parser.add_argument("--version", action="version", version="open-business-finder " + __version__)
    sub = parser.add_subparsers(dest="command", metavar="command")

    reg = sub.add_parser("regions", help="list region / county / locality names and ids of a country")
    reg.add_argument("--country", required=True, help="2-letter ISO code, e.g. TR, DE, US")
    reg.add_argument("--level", default="region", choices=divisions.LEVELS, help="area level (default: region)")
    reg.add_argument("--parent", help="only areas inside this region, e.g. --level county --parent Istanbul")
    reg.add_argument("--release", help="Overture release (default: newest)")
    reg.add_argument("--json", action="store_true", help="print JSON instead of a table")
    reg.add_argument("--no-cache", action="store_true", help="ignore and do not write the local cache")
    reg.add_argument("--divisions-path", help="advanced: local division_area parquet instead of Overture on S3")

    cat = sub.add_parser("categories", help="list Overture category names (optionally filtered)")
    cat.add_argument("query", nargs="?", help="substring, e.g. cafe, dent, beauty")
    cat.add_argument("--limit", type=int, default=50, help="max rows (default 50, 0 = all)")
    cat.add_argument("--json", action="store_true", help="print JSON instead of a table")

    se = sub.add_parser("search", help="list businesses in an area")
    se.add_argument("--country", help="2-letter ISO code (required with --region / --county)")
    se.add_argument("--region", help='region / province / state name, e.g. "Izmir"')
    se.add_argument("--county", help="county / district name inside the region, e.g. Bornova")
    se.add_argument("--category", help="comma separated Overture categories or parents, e.g. cafe,restaurant")
    se.add_argument("--near", metavar="LAT,LON", help="centre point, with --radius-km")
    se.add_argument("--radius-km", type=float, default=1.0, help="radius for --near (default 1)")
    se.add_argument("--bbox", metavar="MINLON,MINLAT,MAXLON,MAXLAT", help="bounding box (fastest way to scope)")
    se.add_argument("--has-website", action="store_true", help="only places with a website")
    se.add_argument("--has-phone", action="store_true", help="only places with a phone number")
    se.add_argument("--min-confidence", type=float, help="Overture confidence 0..1, e.g. 0.6")
    se.add_argument("--limit", type=int, default=500, help="max rows, best confidence first (default 500, 0 = all)")
    se.add_argument("--format", choices=output.FORMATS, help="csv (default), json or geojson")
    se.add_argument("--out", help="write to this file instead of stdout")
    se.add_argument("--release", help="Overture release, e.g. 2026-11-18.0 (default: newest)")
    se.add_argument("--no-cache", action="store_true", help="ignore and do not write the local cache")
    se.add_argument("--quiet", action="store_true", help="no progress on stderr")
    se.add_argument("--places-path", help="advanced: local places parquet file or glob instead of Overture on S3")
    se.add_argument("--divisions-path", help="advanced: local division_area parquet instead of Overture on S3")

    en = sub.add_parser("enrich", help="scan the websites in a results file for WhatsApp, chat, e-mail, phone")
    en.add_argument("input", help="CSV or JSON file written by `obf search`")
    en.add_argument("--out", required=True, help="output file (csv, json)")
    en.add_argument("--format", choices=("csv", "json"), help="default: from the --out extension, else csv")
    en.add_argument("--concurrency", type=int, default=8, help="parallel site fetches (default 8)")
    en.add_argument("--timeout", type=float, default=12.0, help="seconds per site (default 12)")
    en.add_argument("--website-field", default="website", help="column holding the site (default website)")
    en.add_argument("--respect-robots", action="store_true", help="skip sites whose robots.txt disallows it")
    en.add_argument("--quiet", action="store_true", help="no progress on stderr")
    return parser


def _table(rows: List[Dict[str, Any]], cols: Sequence[str]) -> str:
    widths = [max(len(c), *(len(str(r.get(c, ""))) for r in rows)) if rows else len(c) for c in cols]
    lines = ["  ".join(c.ljust(w) for c, w in zip(cols, widths)).rstrip()]
    for row in rows:
        lines.append("  ".join(str(row.get(c, "")).ljust(w) for c, w in zip(cols, widths)).rstrip())
    return "\n".join(lines)


def _cmd_regions(args: argparse.Namespace) -> int:
    rows = divisions.list_areas(
        args.country, args.level, args.parent, release=args.release, source=args.divisions_path,
        use_cache=not args.no_cache, log=stderr_log,
    )
    if args.json:
        json.dump(rows, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        print(_table(rows, ("name", "code", "level", "id")))
        print("%d %s areas" % (len(rows), args.level), file=sys.stderr)
    return 0


def _cmd_categories(args: argparse.Namespace) -> int:
    rows = find_categories(args.query, args.limit or None)
    if args.json:
        json.dump(rows, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        print(_table(rows, ("category", "basic_category", "places_worldwide")))
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    fmt = output.infer_format(args.format, args.out)
    rows = search(
        country=args.country, region=args.region, county=args.county, category=args.category,
        near=args.near, radius_km=args.radius_km, bbox=args.bbox, has_website=args.has_website,
        has_phone=args.has_phone, min_confidence=args.min_confidence,
        limit=args.limit or None, release=args.release, cache_results=not args.no_cache,
        places_path=args.places_path, divisions_path=args.divisions_path,
        progress=None if args.quiet else stderr_log,
    )
    if args.out:
        output.write_file(rows, fmt, args.out)
        if not args.quiet:
            stderr_log("Wrote %d rows to %s" % (len(rows), args.out))
    else:
        output.write(rows, fmt, sys.stdout)
    return 0


def _cmd_enrich(args: argparse.Namespace) -> int:
    rows = enrich.read_rows(args.input)
    fmt = output.infer_format(args.format, args.out)
    if fmt == "geojson":
        raise SearchError("enrich writes csv or json")

    def progress(done: int, total: int) -> None:
        if not args.quiet and (done % 10 == 0 or done == total):
            stderr_log("  scanned %d/%d sites" % (done, total))

    result = enrich.enrich_rows(
        rows, website_field=args.website_field, concurrency=args.concurrency, timeout=args.timeout,
        respect_robots=args.respect_robots, progress=progress,
    )
    output.write_file(result, fmt, args.out)
    if not args.quiet:
        stderr_log("Wrote %d rows to %s" % (len(result), args.out))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")

    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help(sys.stderr)
        return 2
    handlers = {"regions": _cmd_regions, "categories": _cmd_categories, "search": _cmd_search, "enrich": _cmd_enrich}
    try:
        return handlers[args.command](args)
    except (SearchError, divisions.AreaError, enrich.EnrichUnavailable, DependencyError, OSError, ValueError) as exc:
        print("obf: %s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("obf: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
