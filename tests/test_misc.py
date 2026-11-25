import json

from open_business_finder import cache, release
from open_business_finder.categories import find_categories, load_categories
from open_business_finder.enrich import CHANNEL_COLUMNS, enrich_rows


def test_category_list_is_bundled():
    rows = load_categories()
    assert len(rows) > 500
    assert any(r["category"] == "restaurant" for r in rows)
    assert "dent" in find_categories("DENT")[0]["category"]
    assert find_categories("food_and_drink", limit=5)  # parents match through the hierarchy


def test_latest_release_falls_back_when_listing_fails(monkeypatch):
    def boom(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(release.urllib.request, "urlopen", boom)
    assert release.latest_release() == release.DEFAULT_RELEASE
    assert release.resolve_release("2025-01-01.0") == "2025-01-01.0"


class _Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def test_latest_release_parses_listing_and_caches(monkeypatch):
    body = (
        "<ListBucketResult><CommonPrefixes><Prefix>release/2026-10-21.0/</Prefix></CommonPrefixes>"
        "<CommonPrefixes><Prefix>release/2026-11-18.0/</Prefix></CommonPrefixes>"
        "<CommonPrefixes><Prefix>release/2026-11-18.10/</Prefix></CommonPrefixes></ListBucketResult>"
    ).encode()
    monkeypatch.setattr(release.urllib.request, "urlopen", lambda *a, **k: _Resp(body))
    assert release.latest_release() == "2026-11-18.10"

    def boom(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(release.urllib.request, "urlopen", boom)
    assert release.latest_release() == "2026-11-18.10"  # served from the cache
    assert cache.read_json("latest_release.json")["release"] == "2026-11-18.10"


def test_result_cache_roundtrip():
    key = cache.result_key({"a": 1, "b": [2]})
    assert cache.load_result(key) is None
    cache.save_result(key, [{"name": "x"}])
    assert cache.load_result(key) == [{"name": "x"}]
    assert key == cache.result_key({"b": [2], "a": 1})


class FakeResult:
    def __init__(self):
        self.ok, self.error = True, None
        self.channels = ["whatsapp", "email"]
        self.instant_channel = True
        self.social = {"instagram": "shop"}

    def values(self, ch):
        return {"whatsapp": ["905551112233"], "email": ["hi@shop.example"]}.get(ch, [])

    def providers(self, ch):
        return []


def test_enrich_rows_with_fake_detector():
    rows = [
        {"name": "A", "website": "https://a.example"},
        {"name": "B", "website": ""},
        {"name": "C", "website": "https://c.example"},
        {"name": "D", "website": "https://a.example"},
    ]
    seen = []

    def detect(url):
        seen.append(url)
        if "c.example" in url:
            raise RuntimeError("boom")
        return FakeResult()

    out = enrich_rows(rows, detect=detect, concurrency=3)
    assert sorted(seen) == ["https://a.example", "https://c.example"]  # one fetch per distinct site
    assert out[0]["whatsapp"] == ["905551112233"] and out[0]["instant_channel"] is True
    assert out[0]["site_socials"] == ["instagram:shop"]
    assert out[1]["channels"] == [] and out[1]["site_ok"] == ""  # no website: empty columns
    assert out[2]["site_ok"] is False and "boom" in out[2]["site_error"]
    assert out[3]["site_emails"] == ["hi@shop.example"]
    assert set(CHANNEL_COLUMNS) <= set(out[0])
    json.dumps(out)


def test_unknown_category_warning(places_file):
    from open_business_finder import search
    from open_business_finder.categories import unknown_categories

    assert unknown_categories(["cafe", "food_and_drink", "dental_clinic"]) == {}
    assert "coffee_shop" in unknown_categories(["cofee_shop"])["cofee_shop"]
    messages = []
    search(bbox="25,38,30,41.5", category="dentist", places_path=places_file, progress=messages.append)
    assert any("not a known Overture category" in m for m in messages)
