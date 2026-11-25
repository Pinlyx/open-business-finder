"""Fixtures: tiny fake Overture files built with DuckDB at test time. No network."""

from __future__ import annotations

import pytest

from open_business_finder import db

# (id, name, primary, hierarchy, basic, confidence, websites, phones, emails, socials,
#  freeform, locality, status, lon, lat)
CAFE = ["food_and_drink", "casual_eatery", "cafe"]
PLACES = [
    ("p1", "Moda Kahve", "cafe", CAFE, "cafe", 0.9,
     ["https://modakahve.example"], ["+902161110001"], ["info@modakahve.example"],
     ["https://www.instagram.com/modakahve"], "Moda Cad. 1", "Kadikoy", None, 29.02, 40.92),
    ("p2", "Cay Evi", "restaurant", ["food_and_drink", "restaurant"], "restaurant", 0.5,
     [], ["+902161110002"], [], [], "Moda Cad. 2", "Kadikoy", None, 29.03, 40.93),
    ("p3", "Ucgen Disi Kafe", "cafe", CAFE, "cafe", 0.7,
     ["https://ucgendisi.example"], [], [], [], None, None, None, 29.09, 40.99),
    ("p4", "Kapali Kafe", "cafe", CAFE, "cafe", 0.8,
     [], [], [], [], None, None, "closed", 29.02, 40.91),
    ("p5", "Bornova Disci", "dentist", ["health_care", "dentist"], "dentist", 0.8,
     ["https://bornovadisci.example"], ["+902320000005"], [], [], "Ankara Cad. 5", "Bornova", None, 26.30, 38.45),
    ("p6", "Deniz Kafe", "cafe", CAFE, "cafe", 0.6,
     [], [], [], [], None, None, None, 27.50, 40.50),
    ("p7", "Sessiz Kafe", "cafe", CAFE, "cafe", 0.3,
     [], [], [], [], None, "Besiktas", None, 29.50, 41.00),
    ("p8", None, "cafe", CAFE, "cafe", 0.9,
     [], [], [], [], None, None, None, 29.02, 40.925),
    ("p9", "Izmir Kafe", "cafe", CAFE, "cafe", 0.85,
     ["https://izmirkafe.example"], ["+902320000009"], [], [], None, "Izmir", None, 26.50, 38.50),
]

PLACE_COLUMNS = """
    id VARCHAR,
    names STRUCT("primary" VARCHAR),
    {category_columns}
    confidence DOUBLE,
    websites VARCHAR[], phones VARCHAR[], emails VARCHAR[], socials VARCHAR[],
    addresses STRUCT(freeform VARCHAR, locality VARCHAR, postcode VARCHAR, region VARCHAR, country VARCHAR)[],
    operating_status VARCHAR,
    bbox STRUCT(xmin DOUBLE, xmax DOUBLE, ymin DOUBLE, ymax DOUBLE)
"""
TAXONOMY_COLUMNS = (
    'taxonomy STRUCT("primary" VARCHAR, hierarchy VARCHAR[], alternates VARCHAR[]), basic_category VARCHAR,'
)
LEGACY_COLUMNS = 'categories STRUCT("primary" VARCHAR, alternate VARCHAR[]),'


def _rows(legacy: bool):
    out = []
    for (pid, name, prim, hier, basic, conf, webs, phones, emails, socials, free, loc, status, lon, lat) in PLACES:
        addr = [{"freeform": free, "locality": loc, "postcode": None, "region": None, "country": "TR"}]
        box = {"xmin": lon, "xmax": lon, "ymin": lat, "ymax": lat}
        if legacy:
            out.append((pid, {"primary": name}, {"primary": prim, "alternate": []}, conf, webs, phones, emails,
                        socials, addr, status, box))
        else:
            out.append((pid, {"primary": name}, {"primary": prim, "hierarchy": hier, "alternates": []}, basic, conf,
                        webs, phones, emails, socials, addr, status, box))
    return out


def _write_places(path: str, legacy: bool) -> str:
    import duckdb

    columns = PLACE_COLUMNS.format(category_columns=LEGACY_COLUMNS if legacy else TAXONOMY_COLUMNS)
    con = duckdb.connect()
    con.execute("CREATE TABLE p (%s)" % columns)
    n = 11 if legacy else 12
    con.executemany("INSERT INTO p VALUES (%s)" % ",".join("?" * n), _rows(legacy))
    path = path.replace("\\", "/")
    con.execute("COPY p TO '%s' (FORMAT parquet)" % path)
    con.close()
    return path


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("OBF_CACHE_DIR", str(tmp_path / "cache"))


@pytest.fixture(scope="session")
def spatial_available() -> bool:
    return db.has_spatial()


@pytest.fixture
def needs_spatial(spatial_available):
    if not spatial_available:
        pytest.skip("DuckDB spatial extension cannot be loaded here (no network to download it)")


@pytest.fixture
def places_file(tmp_path):
    return _write_places(str(tmp_path / "places.parquet"), legacy=False)


@pytest.fixture
def legacy_places_file(tmp_path):
    """Older Overture releases: `categories` instead of `taxonomy`."""
    return _write_places(str(tmp_path / "places_legacy.parquet"), legacy=True)


def _box(x0, y0, x1, y1) -> str:
    return "POLYGON((%s %s, %s %s, %s %s, %s %s, %s %s))" % (x0, y0, x1, y0, x1, y1, x0, y1, x0, y0)


ISTANBUL = "İstanbul"
IZMIR = "İzmir"
KADIKOY = "Kadıköy"

# (id, subtype, class, region code, name, common names, bbox, wkt)
DIVISIONS = [
    ("r-ist", "region", "land", "TR-34", ISTANBUL, {"en": "Istanbul"}, (28.0, 40.5, 30.0, 41.5),
     _box(28.0, 40.5, 30.0, 41.5)),
    ("r-ist-sea", "region", "maritime", "TR-34", ISTANBUL, {"en": "Istanbul"}, (27.0, 40.0, 28.0, 41.0),
     _box(27.0, 40.0, 28.0, 41.0)),
    ("r-izm", "region", "land", "TR-35", IZMIR, {"en": "Izmir"}, (26.0, 38.0, 27.0, 39.0),
     _box(26.0, 38.0, 27.0, 39.0)),
    ("c-kad", "county", "land", "TR-34", KADIKOY, {}, (29.0, 40.9, 29.1, 41.0),
     "POLYGON((29.0 40.9, 29.1 40.9, 29.0 41.0, 29.0 40.9))"),
    ("c-bor", "county", "land", "TR-35", "Bornova", {}, (26.2, 38.4, 26.4, 38.5), _box(26.2, 38.4, 26.4, 38.5)),
    ("c-mer1", "county", "land", "TR-34", "Merkez", {}, (29.4, 40.9, 29.6, 41.1), _box(29.4, 40.9, 29.6, 41.1)),
    ("c-mer2", "county", "land", "TR-35", "Merkez", {}, (26.5, 38.4, 26.6, 38.6), _box(26.5, 38.4, 26.6, 38.6)),
]


@pytest.fixture
def divisions_file(tmp_path, needs_spatial):
    import duckdb

    con = duckdb.connect()
    db._load_extension(con, "spatial")
    con.execute(
        """CREATE TABLE d (id VARCHAR, country VARCHAR, subtype VARCHAR, class VARCHAR, region VARCHAR,
           names STRUCT("primary" VARCHAR, common MAP(VARCHAR, VARCHAR)),
           bbox STRUCT(xmin DOUBLE, xmax DOUBLE, ymin DOUBLE, ymax DOUBLE), geometry GEOMETRY)"""
    )
    for did, sub, cls, code, name, common, (x0, y0, x1, y1), wkt in DIVISIONS:
        con.execute(
            "INSERT INTO d VALUES (?, 'TR', ?, ?, ?, {'primary': ?, 'common': map_from_entries(?)}, "
            "{'xmin': ?, 'xmax': ?, 'ymin': ?, 'ymax': ?}, ST_GeomFromText(?))",
            [did, sub, cls, code, name, [{"key": k, "value": v} for k, v in common.items()],
             x0, x1, y0, y1, wkt],
        )
    path = str(tmp_path / "divisions.parquet").replace("\\", "/")
    con.execute("COPY d TO '%s' (FORMAT parquet)" % path)
    con.close()
    return path
