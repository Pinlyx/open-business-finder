---
name: open-business-finder
description: Build a lead list or market map of local businesses in any country (by region, district, category, radius or bounding box) from open Overture Maps data with the `obf` CLI. Use when asked to find, list or export businesses such as cafes, dentists or salons in a city or district, optionally with phone, website, e-mail and detected WhatsApp/live chat. No API key, no browser, no Google scraping.
---

# open-business-finder

Turns "find me N businesses of type X in place Y" into a CSV, JSON or GeoJSON file using the `obf` command (`open-business-finder`). Data is Overture Maps places (open data), so there is no key and no scraping.

## Install (once)

```bash
pip install git+https://github.com/Pinlyx/open-business-finder
# for website contact scanning as well:
pip install "open-business-finder[channels] @ git+https://github.com/Pinlyx/open-business-finder"
```

Or run without installing: `uvx --from git+https://github.com/Pinlyx/open-business-finder obf --help`.

## Workflow

1. **Find the category name.** Wrong names return nothing (the tool prints a warning with suggestions).
   `obf categories cafe` or `obf categories dent --json`. Parents such as `food_and_drink` also work.
2. **Find the area name.** `obf regions --country TR` (first level: province or state), then
   `obf regions --country TR --level county --parent İstanbul` (districts). Names are matched ignoring case and accents.
3. **Search.** Scope by area, circle or box:

   ```bash
   obf search --country TR --region İstanbul --county Kadıköy --category cafe --has-website --limit 200 --out leads.csv
   obf search --near 52.52,13.405 --radius-km 2 --category dental_clinic --has-phone --format geojson --out map.geojson
   obf search --bbox 29.02,40.98,29.04,40.99 --category restaurant --out small.csv
   ```

4. **Optional: detect contact channels on the websites.**
   `obf enrich leads.csv --out leads-channels.csv --concurrency 8`
   Adds `whatsapp`, `telegram`, `live_chat`, `site_emails`, `site_phones`, `site_socials`, `instant_channel`, `site_ok`.

## Rules of thumb

- Progress goes to stderr; the data goes to stdout or `--out`. Use `--quiet` to silence progress.
- Remote queries take roughly 15 to 30 seconds for a district or city, longer for big unfiltered areas. Prefer a district or `--bbox`, add `--category`, `--has-website` and `--min-confidence 0.6` to shrink the work. Identical queries are cached.
- Output fields: `id, name, category, alt_categories, confidence, website, phone, email, socials, address, locality, country, lat, lon, source` (plus `distance_km` with `--near`).
- Overture has no ratings or reviews, and phone/website coverage varies by country. Say so instead of inventing numbers. Check coverage with `--has-phone` / `--has-website` counts.
- `website` sometimes holds a social profile URL; treat rows with a real company domain as the website leads.
- Default `--limit` is 500, best confidence first. Use `--limit 0` for everything in the area.

## Responsible use

A business list is not consent to be contacted. Do not send bulk e-mail, SMS, WhatsApp or Telegram messages to the people on it without a valid legal basis or permission, honour opt-outs, and follow local rules (GDPR/ePrivacy, CAN-SPAM, KVKK and similar). Use `--respect-robots` with `obf enrich`.

## Attribution

When results are published or shared, credit: Places: Overture Maps Foundation (CDLA-Permissive-2.0). Boundaries: (c) OpenStreetMap contributors, Overture Maps Foundation (ODbL 1.0).
