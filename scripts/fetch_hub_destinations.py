"""Build `config/hub_destinations.json` — all UA destinations from each hub,
with domestic vs international classification.

Source: Wikipedia airport pages. These have comprehensive "Airlines and
destinations" tables that list every UA route (including seasonal/future).

Usage:
  python scripts/fetch_hub_destinations.py              # normal
  python scripts/fetch_hub_destinations.py --verbose    # print unmatched names

Wikipedia isn't bot-blocked, so plain HTTP works — no Playwright needed.
"""

import argparse
import html
import json
import logging
import re
import sys
from pathlib import Path

import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_wiki_name_index import lookup, country_of, city_of

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

HUBS = [
    ("EWR", "Newark Liberty International Airport"),
    ("IAD", "Washington Dulles International Airport"),
    ("SFO", "San Francisco International Airport"),
    ("LAX", "Los Angeles International Airport"),
    ("IAH", "George Bush Intercontinental Airport"),
]

LINK_RE = re.compile(r'<a href="/wiki/([^"]+)" title="([^"]+)">([^<]+)</a>')


def fetch_wiki(title: str) -> str:
    url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
    req = urllib.request.Request(url, headers={"User-Agent": "northstar-scraper/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def extract_ua_row(html: str) -> str | None:
    """Find the big <tr> in the Airlines and destinations table where
    United Airlines (not Cargo, not Express) appears as the airline cell."""
    rows = re.findall(r'<tr>(.*?)</tr>', html, re.DOTALL)
    for row in rows:
        if '>United Airlines<' not in row:
            continue
        if 'Cargo' in row:
            continue
        # The destinations row is long; the market-share/stats row is short
        if len(row) > 1500:
            return row
    return None


def parse_destinations(ua_row: str, hub_iata: str, verbose: bool = False):
    """Return list of dicts with iata, city, name, country, international (bool)."""
    seen = set()
    results = []
    unmatched = []

    for m in LINK_RE.finditer(ua_row):
        href = html.unescape(m.group(1))
        title = html.unescape(m.group(2))
        display = html.unescape(m.group(3))
        # Only consider links that point to airport articles
        if 'airport' not in title.lower():
            continue
        iata = lookup(title)
        if not iata:
            unmatched.append(title)
            continue
        if iata == hub_iata or iata in seen:
            continue
        seen.add(iata)
        country = country_of(iata)
        results.append({
            "iata": iata,
            "city": city_of(iata) or display,
            "wiki_title": title,
            "country": country,
            "international": country != "US",
        })

    if verbose and unmatched:
        logger.info(f"  unmatched titles ({len(set(unmatched))}):")
        for t in sorted(set(unmatched)):
            logger.info(f"    - {t}")
    elif unmatched:
        logger.info(f"  {len(set(unmatched))} unmatched airport titles "
                    f"(rerun with --verbose to list)")

    return sorted(results, key=lambda d: d['iata'])


def main(verbose: bool):
    output: dict = {}
    for code, wiki_title in HUBS:
        logger.info(f"{code}: fetching {wiki_title}")
        try:
            html = fetch_wiki(wiki_title)
        except Exception as e:
            logger.error(f"{code}: fetch failed — {e}")
            continue

        ua_row = extract_ua_row(html)
        if not ua_row:
            logger.error(f"{code}: no United Airlines destinations row found")
            continue

        destinations = parse_destinations(ua_row, code, verbose=verbose)
        intl = [d for d in destinations if d['international']]
        dom = [d for d in destinations if not d['international']]

        logger.info(
            f"{code}: {len(destinations)} total — "
            f"{len(intl)} international, {len(dom)} domestic"
        )

        output[code] = {
            "hub": code,
            "source": f"https://en.wikipedia.org/wiki/{wiki_title.replace(' ', '_')}",
            "destinations": destinations,
        }

    out = Path("config/hub_destinations.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(output, indent=2))
    logger.info(f"wrote {out}")

    print()
    print("Summary:")
    for code, data in output.items():
        intl = sorted(d['iata'] for d in data['destinations'] if d['international'])
        dom = sorted(d['iata'] for d in data['destinations'] if not d['international'])
        print(f"  {code}: {len(intl)} intl + {len(dom)} dom")
        print(f"    intl: {', '.join(intl)}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--verbose", action="store_true", help="List unmatched Wikipedia titles")
    args = p.parse_args()
    main(verbose=args.verbose)
