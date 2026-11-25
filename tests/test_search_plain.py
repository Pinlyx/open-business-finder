"""Query layer without polygons: runs without the spatial extension."""

import pytest

from open_business_finder import SearchError, search

WIDE = "25,38,30,41.5"


def names(rows):
    return [r["name"] for r in rows]


def test_bbox_and_category(places_file):
    rows = search(bbox="29.0,40.9,29.1,41.0", category="cafe", places_path=places_file)
    # closed place and nameless place are dropped; best confidence first
    assert names(rows) == ["Moda Kahve", "Ucgen Disi Kafe"]
    assert rows[0]["category"] == "cafe"
    assert rows[0]["source"] == "overture:local"


def test_parent_category_matches_hierarchy(places_file):
    rows = search(bbox="29.0,40.9,29.1,41.0", category="food_and_drink", places_path=places_file)
    assert set(names(rows)) == {"Moda Kahve", "Cay Evi", "Ucgen Disi Kafe"}


def test_multiple_categories(places_file):
    rows = search(bbox=WIDE, category="dentist, restaurant", places_path=places_file)
    assert set(names(rows)) == {"Bornova Disci", "Cay Evi"}


def test_category_normalisation_and_rejection(places_file):
    # "Health-Care" is normalised to the parent key health_care, which matches through the hierarchy
    assert names(search(bbox=WIDE, category="Health-Care", places_path=places_file)) == ["Bornova Disci"]
    assert search(bbox=WIDE, category="no_such_category", places_path=places_file) == []
    with pytest.raises(SearchError):
        search(bbox=WIDE, category="cafe'); DROP TABLE x;--", places_path=places_file)


def test_has_website_has_phone_confidence(places_file):
    web = search(bbox=WIDE, has_website=True, places_path=places_file)
    assert all(r["website"] for r in web) and len(web) == 4
    phone = search(bbox=WIDE, has_phone=True, places_path=places_file)
    assert all(r["phone"] for r in phone) and len(phone) == 4
    both = search(bbox=WIDE, has_website=True, has_phone=True, category="cafe", places_path=places_file)
    assert names(both) == ["Moda Kahve", "Izmir Kafe"]
    sure = search(bbox=WIDE, min_confidence=0.8, places_path=places_file)
    assert all(r["confidence"] >= 0.8 for r in sure)
    assert "Cay Evi" not in names(sure)


def test_near_radius_sorted_by_distance(places_file):
    rows = search(near="40.92,29.02", radius_km=2, places_path=places_file)
    assert names(rows) == ["Moda Kahve", "Cay Evi"]
    assert rows[0]["distance_km"] < rows[1]["distance_km"] < 2
    assert search(near="40.92,29.02", radius_km=0.05, places_path=places_file)[0]["name"] == "Moda Kahve"
    far = search(near="40.92,29.02", radius_km=30, places_path=places_file)
    assert "Ucgen Disi Kafe" in names(far) and "Bornova Disci" not in names(far)


def test_limit_and_order(places_file):
    rows = search(bbox=WIDE, limit=2, places_path=places_file)
    assert names(rows) == ["Moda Kahve", "Izmir Kafe"]  # 0.9 then 0.85
    assert len(search(bbox=WIDE, limit=None, places_path=places_file)) == 7


def test_fields_and_address(places_file):
    row = search(bbox="29.0,40.9,29.1,41.0", category="cafe", places_path=places_file)[0]
    assert list(row)[:15] == [
        "id", "name", "category", "alt_categories", "confidence", "website", "phone", "email",
        "socials", "address", "locality", "country", "lat", "lon", "source",
    ]
    assert row["website"] == "https://modakahve.example"
    assert row["phone"] == "+902161110001"
    assert row["email"] == "info@modakahve.example"
    assert row["socials"] == ["https://www.instagram.com/modakahve"]
    assert row["address"] == "Moda Cad. 1, Kadikoy"
    assert (row["lat"], row["lon"]) == (40.92, 29.02)
    assert "distance_km" not in row


def test_legacy_categories_schema(legacy_places_file):
    rows = search(bbox="29.0,40.9,29.1,41.0", category="cafe", places_path=legacy_places_file)
    assert names(rows) == ["Moda Kahve", "Ucgen Disi Kafe"]


def test_disjoint_boxes_return_nothing(places_file):
    assert search(bbox="0,0,1,1", near="40.92,29.02", places_path=places_file) == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {},  # no scope
        {"region": "X"},  # region without country
        {"bbox": "1,2,3"},
        {"bbox": "10,0,5,1"},
        {"bbox": "0,0,1,1", "min_confidence": 2},
        {"near": "95,0"},
        {"near": "1,1", "radius_km": 0},
        {"bbox": "0,0,1,1", "limit": -1},
    ],
)
def test_bad_arguments(kwargs, places_file):
    with pytest.raises(SearchError):
        search(places_path=places_file, **kwargs)
