import csv
import io
import json

import pytest

from open_business_finder import output
from open_business_finder.cli import build_parser, main

ROWS = [
    {"id": "a", "name": "Cafe Çay", "category": "cafe", "alt_categories": ["bar", "restaurant"],
     "confidence": 0.9, "website": None, "phone": "+90 1", "email": None,
     "socials": ["https://x.example/a", "https://y.example/a"], "address": "Street, City",
     "locality": None, "country": "TR", "lat": 40.9, "lon": 29.0, "source": "overture:test"},
]


def test_csv_flattens_lists_and_quotes():
    rows = [dict(ROWS[0], name='He said "hi", ok')]
    text = output.render(rows, "csv")
    parsed = list(csv.DictReader(io.StringIO(text)))
    assert parsed[0]["name"] == 'He said "hi", ok'
    assert parsed[0]["alt_categories"] == "bar;restaurant"
    assert parsed[0]["socials"] == "https://x.example/a | https://y.example/a"
    assert parsed[0]["website"] == ""
    assert text.splitlines()[0].startswith("id,name,category,alt_categories,confidence,website")


def test_json_roundtrip_keeps_unicode():
    data = json.loads(output.render(ROWS, "json"))
    assert data[0]["name"] == "Cafe Çay" and data[0]["alt_categories"] == ["bar", "restaurant"]
    assert "\\u00c7" not in output.render(ROWS, "json")


def test_geojson_point_order_is_lon_lat():
    fc = json.loads(output.render(ROWS, "geojson"))
    assert fc["type"] == "FeatureCollection"
    feat = fc["features"][0]
    assert feat["geometry"] == {"type": "Point", "coordinates": [29.0, 40.9]}
    assert "lat" not in feat["properties"] and feat["properties"]["name"] == "Cafe Çay"


def test_infer_format():
    assert output.infer_format(None, "x.json") == "json"
    assert output.infer_format(None, "x.geojson") == "geojson"
    assert output.infer_format(None, "x.csv") == "csv"
    assert output.infer_format(None, None) == "csv"
    assert output.infer_format("json", "x.csv") == "json"


def test_parser_search_arguments():
    args = build_parser().parse_args([
        "search", "--country", "TR", "--region", "Izmir", "--county", "Bornova", "--category", "cafe,restaurant",
        "--near", "41.0,29.0", "--radius-km", "2", "--bbox", "1,2,3,4", "--has-website", "--has-phone",
        "--min-confidence", "0.6", "--limit", "10", "--format", "geojson", "--out", "o.geojson",
    ])
    assert (args.command, args.country, args.region, args.county) == ("search", "TR", "Izmir", "Bornova")
    assert args.category == "cafe,restaurant" and args.near == "41.0,29.0" and args.radius_km == 2.0
    assert args.has_website and args.has_phone and args.min_confidence == 0.6 and args.limit == 10
    assert args.format == "geojson" and args.out == "o.geojson"


def test_parser_rejects_bad_input():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["search", "--format", "xml"])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["regions"])  # --country is required
    with pytest.raises(SystemExit):
        build_parser().parse_args(["regions", "--country", "TR", "--level", "street"])


def test_cli_search_end_to_end_json(places_file, capsys):
    code = main(["search", "--bbox", "29.0,40.9,29.1,41.0", "--category", "cafe", "--format", "json",
                 "--places-path", places_file, "--quiet"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert [r["name"] for r in data] == ["Moda Kahve", "Ucgen Disi Kafe"]


def test_cli_search_writes_file_and_infers_format(places_file, tmp_path):
    out = tmp_path / "r.geojson"
    assert main(["search", "--bbox", "25,38,30,41.5", "--places-path", places_file, "--out", str(out), "--quiet"]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["type"] == "FeatureCollection"


def test_cli_error_is_clean(capsys):
    assert main(["search"]) == 1
    assert "obf: Give a scope" in capsys.readouterr().err
    assert main(["search", "--region", "X"]) == 1


def test_cli_categories(capsys):
    assert main(["categories", "cafe", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert any(r["category"] == "cafe" for r in data)
    assert all("cafe" in r["category"] or "cafe" in r["hierarchy"] or "cafe" in r["basic_category"] for r in data)


def test_cli_no_command_prints_help():
    assert main([]) == 2
