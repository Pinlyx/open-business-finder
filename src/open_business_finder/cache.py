"""Local cache: region geometries, resolved release, repeated query results."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional


def cache_dir() -> Path:
    """``$OBF_CACHE_DIR`` or ``~/.cache/open-business-finder``."""
    override = os.environ.get("OBF_CACHE_DIR")
    base = Path(override).expanduser() if override else Path.home() / ".cache" / "open-business-finder"
    base.mkdir(parents=True, exist_ok=True)
    return base


def subdir(name: str) -> Path:
    path = cache_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def result_key(params: Dict[str, Any]) -> str:
    blob = json.dumps(params, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def load_result(key: str) -> Optional[list]:
    path = subdir("results") / (key + ".json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_result(key: str, rows: list) -> None:
    path = subdir("results") / (key + ".json")
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def read_json(name: str, max_age: Optional[float] = None) -> Optional[Any]:
    path = cache_dir() / name
    try:
        if max_age is not None and time.time() - path.stat().st_mtime > max_age:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(name: str, data: Any) -> None:
    try:
        (cache_dir() / name).write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass
