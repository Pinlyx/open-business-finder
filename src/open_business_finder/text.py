"""Text helpers: accent-insensitive folding and safe output strings."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

_LONE_SURROGATE = re.compile("[\ud800-\udfff]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPECIAL = str.maketrans({"ı": "i", "İ": "i", "ł": "l", "Ł": "l", "ø": "o", "Ø": "o", "đ": "d", "Đ": "d", "ß": "ss", "æ": "ae", "œ": "oe"})


def fold(value: str) -> str:
    """Case, accent and dotted/dotless-i insensitive key.

    ``fold("İzmir") == fold("izmir") == fold("IZMIR")`` and
    ``fold("Şişli") == fold("sisli")``.
    """
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.translate(_SPECIAL).casefold()
    text = re.sub(r"[\s\-_'’.]+", " ", text)
    return text.strip()


def clean_text(value: Any) -> Optional[str]:
    """Make a string safe to write out as UTF-8.

    Some real place names carry lone surrogate code points (half of an emoji,
    left over from a truncated source record). They crash encoders, so they are
    dropped, together with NUL and other control characters. Returns None for
    empty results.
    """
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    text = _LONE_SURROGATE.sub("", text)
    text = _CONTROL.sub("", text).strip()
    return text or None
