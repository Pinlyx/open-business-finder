# Contributing

Bug reports and pull requests are welcome. The most useful reports are a query that returned the wrong area or missed obvious places, with the exact command and the Overture release it ran against.

1. Fork, then `pip install -e ".[test]"`.
2. Add a test that fails before your change. Tests build tiny fake Overture parquet files with DuckDB and run the query layer against them through the `places_path` / `divisions_path` arguments. They must pass offline and must never touch the live network.
3. Run `python -m pytest -rs`. Tests that need the DuckDB spatial extension are skipped when it cannot be loaded, so run them at least once on a machine that can download it.
4. Keep runtime dependencies to `duckdb` and the standard library. Supported Python: 3.10 to 3.13.
5. Open an issue first for larger changes.
