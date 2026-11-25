# Changelog

## 0.1.0 - 2026-11-20

- First release: `obf regions`, `obf categories`, `obf search`, `obf enrich` and the `search()` Python function.
- Businesses come from Overture Maps places, areas from Overture divisions (land polygons only).
- Region and district filtering is geometric (bounding box prune, then point-in-polygon on the small result).
- Local cache for boundaries, the newest release name and repeated queries.
- CSV, JSON and GeoJSON output; optional website contact-channel enrichment through contact-channel-detector.
