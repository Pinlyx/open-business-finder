"""Region and county resolution: needs the DuckDB spatial extension."""

import pytest

from open_business_finder import regions, search
from open_business_finder.divisions import AreaError

pytestmark = pytest.mark.spatial


def names(rows):
    return [r["name"] for r in rows]


def run(places_file, divisions_file, **kw):
    return search(country="TR", places_path=places_file, divisions_path=divisions_file, **kw)


def test_region_accent_insensitive(places_file, divisions_file):
    for spelling in ("İstanbul", "istanbul", "ISTANBUL", "Istanbul"):
        rows = run(places_file, divisions_file, region=spelling, category="cafe")
        assert names(rows) == ["Moda Kahve", "Ucgen Disi Kafe", "Sessiz Kafe"], spelling


def test_maritime_polygon_is_ignored(places_file, divisions_file):
    # "Deniz Kafe" sits inside the maritime polygon of Istanbul only.
    rows = run(places_file, divisions_file, region="Istanbul")
    assert "Deniz Kafe" not in names(rows)
    assert "Izmir Kafe" not in names(rows)


def test_regions_listing_has_no_duplicates(divisions_file):
    rows = regions("TR", "region", source=divisions_file)
    assert [r["name"] for r in rows] == ["İstanbul", "İzmir"]
    assert {r["code"] for r in rows} == {"TR-34", "TR-35"}


def test_county_uses_real_polygon_not_bbox(places_file, divisions_file):
    # Kadikoy is a triangle: "Ucgen Disi Kafe" is inside its bbox but outside the polygon.
    rows = run(places_file, divisions_file, region="Istanbul", county="Kadikoy", category="cafe")
    assert names(rows) == ["Moda Kahve"]


def test_county_without_region_and_ambiguity(places_file, divisions_file):
    assert names(run(places_file, divisions_file, county="Bornova")) == ["Bornova Disci"]
    with pytest.raises(AreaError, match="several regions"):
        run(places_file, divisions_file, county="Merkez")
    # with the region it resolves
    assert run(places_file, divisions_file, region="Izmir", county="Merkez") == []


def test_unknown_area_suggests(places_file, divisions_file):
    with pytest.raises(AreaError, match="Did you mean"):
        run(places_file, divisions_file, region="Istanbull")
    with pytest.raises(AreaError):
        run(places_file, divisions_file, region="Izmir", county="Kadikoy")


def test_regions_parent_filter(divisions_file):
    rows = regions("TR", "county", parent="Istanbul", source=divisions_file)
    assert [r["name"] for r in rows] == ["Kadıköy", "Merkez"]


def test_region_plus_bbox_and_filters(places_file, divisions_file):
    rows = run(places_file, divisions_file, region="Istanbul", bbox="29.4,40.9,29.6,41.1")
    assert names(rows) == ["Sessiz Kafe"]
    with_phone = run(places_file, divisions_file, region="Istanbul", has_phone=True)
    assert names(with_phone) == ["Moda Kahve", "Cay Evi"]
