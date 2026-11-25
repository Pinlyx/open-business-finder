"""DuckDB connection setup."""

from __future__ import annotations

from typing import Any

from .release import S3_REGION


class DependencyError(RuntimeError):
    """A DuckDB extension that is needed could not be loaded."""


def is_remote(path: str) -> bool:
    return path.lower().startswith(("s3://", "http://", "https://"))


def sql_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _load_extension(con: Any, name: str) -> None:
    try:
        con.execute("LOAD %s" % name)
        return
    except Exception:
        pass
    try:
        con.execute("INSTALL %s" % name)
        con.execute("LOAD %s" % name)
    except Exception as exc:
        raise DependencyError(
            "DuckDB extension '%s' could not be loaded (%s). It is downloaded once from "
            "extensions.duckdb.org, so the first run needs internet access." % (name, exc)
        ) from exc


def connect(remote: bool = False, spatial: bool = False) -> Any:
    """New in-memory DuckDB connection with the extensions a query needs."""
    import duckdb

    con = duckdb.connect()
    if remote:
        _load_extension(con, "httpfs")
        con.execute("SET s3_region=%s" % sql_literal(S3_REGION))
    if spatial:
        _load_extension(con, "spatial")
    return con


def has_spatial() -> bool:
    """True when the spatial extension is installed or can be downloaded."""
    try:
        con = connect(spatial=True)
        con.close()
        return True
    except Exception:
        return False
