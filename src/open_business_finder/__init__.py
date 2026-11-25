"""Find local businesses in any country from open map data (Overture Maps)."""

__version__ = "0.1.0"

from .categories import find_categories  # noqa: E402
from .divisions import list_areas as regions  # noqa: E402
from .enrich import enrich_rows  # noqa: E402
from .release import DEFAULT_RELEASE, latest_release  # noqa: E402
from .search import FIELDS, SearchError, search  # noqa: E402

__all__ = [
    "DEFAULT_RELEASE",
    "FIELDS",
    "SearchError",
    "enrich_rows",
    "find_categories",
    "latest_release",
    "regions",
    "search",
    "__version__",
]
