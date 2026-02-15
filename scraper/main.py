#!/usr/bin/env python3
"""
Northstar — United Airlines seat availability monitor.

Orchestrates scraping across routes and dates with tiered refresh logic.
"""

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from .browser import BrowserManager
from .rate_limiter import AdaptiveRateLimiter
from .route_discovery import auto_discover_flights
from .flight_scraper import scrape_flight
from .models import FlightData

logger = logging.getLogger(__name__)

# Tiered refresh thresholds (seconds)
REFRESH_TIERS = {
    'imminent': 0,       # 4-24h out: always re-scrape
    'soon': 8 * 3600,    # 24-48h out: re-scrape if > 8 hours stale
    'upcoming': 16 * 3600,  # 48-72h out: re-scrape if > 16 hours stale
}

MAX_RETRIES = 2
MAX_CONSECUTIVE_FAILURES = 10


def load_config(config_path: str = "config/routes.json") -> Dict:
    """Load route configuration."""
    path = Path(config_path)
    if not path.exists():
        logger.warning(f"Config not found at {config_path}, using defaults")
        return {
            "routes": [{"origin": "EWR", "destination": "LHR"}],
            "days_ahead": 3,
            "delay_min": 3,
            "delay_max": 7,
            "headless": True,
            "context_ttl": 15,
        }

    with open(path) as f:
        return json.load(f)


def load_latest_data(data_path: str = "data/latest.json") -> Dict:
    """Load the latest merged flight data."""
    path = Path(data_path)
    if not path.exists():
        return {"last_updated": None, "flights": {}}

    with open(path) as f:
        return json.load(f)


def save_latest_data(data: Dict, data_path: str = "data/latest.json"):
    """Save the merged flight data."""
    path = Path(data_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def should_scrape_flight(
    flight_key: str,
    departure_dt: datetime,
    latest_data: Dict,
    force_refresh: bool = False,
) -> bool:
    """Determine if a flight needs to be scraped based on tiered refresh logic."""
    if force_refresh:
        return True

    now = datetime.utcnow()
    hours_until_departure = (departure_dt - now).total_seconds() / 3600

    # Already departed or departing very soon — skip
    if hours_until_departure < 4:
        return False

    existing = latest_data.get("flights", {}).get(flight_key)
    if not existing:
        return True  # Never scraped

    last_scraped = datetime.fromisoformat(existing["last_scraped"].replace("Z", "+00:00")).replace(tzinfo=None)
    age_seconds = (now - last_scraped).total_seconds()

    if hours_until_departure <= 24:
        return True  # Always re-scrape imminent flights
    elif hours_until_departure <= 48:
        return age_seconds > REFRESH_TIERS['soon']
    else:
        return age_seconds > REFRESH_TIERS['upcoming']


def prune_departed(latest_data: Dict) -> Dict:
    """Remove departed flights from latest data."""
    now = datetime.utcnow()
    flights = latest_data.get("flights", {})
    pruned = {}

    for key, entry in flights.items():
        flight = entry.get("flight_data", {})
        flight_date = flight.get("flight_date", "")
        if flight_date:
            try:
                # Keep flights from today and future
                fd = datetime.strptime(flight_date, "%Y-%m-%d")
                if fd.date() >= now.date():
                    pruned[key] = entry
            except ValueError:
                pruned[key] = entry
        else:
            pruned[key] = entry

    removed = len(flights) - len(pruned)
    if removed > 0:
        logger.info(f"Pruned {removed} departed flights from latest data")

    latest_data["flights"] = pruned
    return latest_data


async def run_scraper(
    config_path: str = "config/routes.json",
    routes_filter: Optional[List[str]] = None,
    force_refresh: bool = False,
    headless: bool = True,
) -> List[FlightData]:
    """Main scraper orchestration.

    Args:
        config_path: Path to routes.json config
        routes_filter: Optional list of specific routes to scrape (e.g. ["EWR-LHR", "SFO-NRT"])
        force_refresh: Bypass tiered staleness checks, re-scrape everything
        headless: Run browser in headless mode

    Returns:
        List of all scraped FlightData objects from this run
    """
    config = load_config(config_path)
    latest_data = load_latest_data()
    latest_data = prune_departed(latest_data)

    days_ahead = config.get("days_ahead", 3)
    context_ttl = config.get("context_ttl", 15)

    browser = BrowserManager(headless=headless, context_ttl=context_ttl)
    limiter = AdaptiveRateLimiter(
        base_min=config.get("delay_min", 3),
        base_max=config.get("delay_max", 7),
    )

    await browser.start()

    all_flights: List[FlightData] = []
    errors: List[Dict] = []
    skipped = 0
    run_timestamp = datetime.utcnow().isoformat() + "Z"
    run_start = time.time()

    try:
        routes = config.get("routes", [])

        # Apply route filter
        if routes_filter:
            filter_set = {r.upper() for r in routes_filter}
            routes = [r for r in routes if f"{r['origin']}-{r['destination']}" in filter_set]
            route_names = [f"{r['origin']}-{r['destination']}" for r in routes]
            logger.info(f"Filtered to {len(routes)} routes: {route_names}")

        existing_count = len(latest_data.get("flights", {}))
        logger.info("=" * 70)
        logger.info("NORTHSTAR SCRAPE STARTING")
        logger.info(f"  Routes: {len(routes)} | Days ahead: {days_ahead} | Force refresh: {force_refresh}")
        logger.info(f"  Existing flights in latest.json: {existing_count}")
        logger.info(f"  Headless: {headless} | Context TTL: {context_ttl}")
        logger.info("=" * 70)

        for route_idx, route in enumerate(routes):
            origin = route["origin"]
            dest = route["destination"]
            route_key = f"{origin}-{dest}"
            consecutive_failures = 0
            route_start = time.time()
            route_scraped = 0
            route_skipped = 0
            route_errors = 0

            pct = ((route_idx) / len(routes)) * 100
            logger.info("")
            logger.info(f"{'=' * 50}")
            logger.info(f"[{route_idx + 1}/{len(routes)}] {route_key}  ({pct:.0f}% complete)")
            logger.info(f"{'=' * 50}")

            for day_offset in range(days_ahead):
                target_date = datetime.now() + timedelta(days=day_offset)
                date_str = target_date.strftime("%Y-%m-%d")
                day_name = target_date.strftime("%a")

                logger.info(f"  {route_key} | {date_str} ({day_name}) — discovering flights...")

                # Discover flights on this route+date
                nonstop_flights, connections = await auto_discover_flights(
                    browser, origin, dest, target_date
                )

                if not nonstop_flights:
                    logger.info(f"  {route_key} | {date_str} — no nonstop UA flights")
                    continue

                logger.info(f"  {route_key} | {date_str} — found {len(nonstop_flights)} flights: UA{', UA'.join(str(f) for f in nonstop_flights)}")

                for flight_num in nonstop_flights:
                    flight_key = f"UA{flight_num}_{date_str}"

                    # Check tiered refresh logic
                    if not should_scrape_flight(flight_key, target_date, latest_data, force_refresh):
                        skipped += 1
                        route_skipped += 1
                        logger.info(f"    UA{flight_num} {date_str} — skipped (data still fresh)")
                        continue

                    # Retry loop
                    success = False
                    for attempt in range(MAX_RETRIES + 1):
                        await limiter.wait()

                        result = await scrape_flight(
                            browser, flight_num, target_date, origin, dest
                        )

                        if result:
                            all_flights.append(result)
                            limiter.record_success()
                            consecutive_failures = 0
                            route_scraped += 1

                            # Merge into latest data
                            latest_data.setdefault("flights", {})[flight_key] = {
                                "flight_data": result.to_dict(),
                                "last_scraped": run_timestamp,
                            }

                            # Verbose per-flight result
                            j = result
                            logger.info(
                                f"    UA{flight_num} {date_str} — "
                                f"J: {j.polaris_available}/{j.polaris_capacity} (delta:{j.polaris_delta:+d}, UG:{j.polaris_upgrade_count}, SA:{j.polaris_sa_count}) | "
                                f"PP: {j.premium_plus_available}/{j.premium_plus_capacity} | "
                                f"Y: {j.economy_available}/{j.economy_capacity} | "
                                f"{j.aircraft_type}"
                            )

                            success = True
                            break
                        else:
                            limiter.record_failure()
                            consecutive_failures += 1

                            if attempt < MAX_RETRIES:
                                logger.warning(f"    UA{flight_num} {date_str} — FAILED, retrying ({attempt + 2}/{MAX_RETRIES + 1})...")
                                await asyncio.sleep(10)

                    if not success:
                        route_errors += 1
                        errors.append({
                            "flight": f"UA{flight_num}",
                            "date": date_str,
                            "route": route_key,
                        })
                        logger.error(f"    UA{flight_num} {date_str} — FAILED after {MAX_RETRIES + 1} attempts")

                    # Abort route on too many consecutive failures
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        logger.error(
                            f"  ABORTING {route_key}: {consecutive_failures} consecutive failures"
                        )
                        break

                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    break

            route_elapsed = time.time() - route_start
            logger.info(f"  {route_key} done: {route_scraped} scraped, {route_skipped} skipped, {route_errors} errors ({route_elapsed:.0f}s)")

            # Delay between routes
            if route_idx < len(routes) - 1:
                await asyncio.sleep(3)

    finally:
        await browser.stop()

    # Save latest data
    latest_data["last_updated"] = run_timestamp
    save_latest_data(latest_data)

    # Save timestamped snapshot
    ts_dir = Path("data") / datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    ts_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "run_timestamp": run_timestamp,
        "routes_processed": len(routes),
        "flights_scraped": len(all_flights),
        "flights_skipped_fresh": skipped,
        "errors": len(errors),
        "error_details": errors,
    }
    with open(ts_dir / "summary.json", 'w') as f:
        json.dump(summary, f, indent=2)
    with open(ts_dir / "flights.json", 'w') as f:
        json.dump([fd.to_dict() for fd in all_flights], f, indent=2)

    run_elapsed = time.time() - run_start
    total_in_latest = len(latest_data.get("flights", {}))

    # Print final summary
    logger.info("")
    logger.info("=" * 70)
    logger.info("NORTHSTAR SCRAPE COMPLETE")
    logger.info("=" * 70)
    logger.info(f"  Duration:         {run_elapsed / 60:.1f} minutes ({run_elapsed:.0f}s)")
    logger.info(f"  Flights scraped:  {len(all_flights)}")
    logger.info(f"  Flights skipped:  {skipped} (data still fresh)")
    logger.info(f"  Errors:           {len(errors)}")
    logger.info(f"  Total in latest:  {total_in_latest} flights across all routes")
    logger.info(f"  Data saved to:    {ts_dir}/")

    if errors:
        logger.info("")
        logger.info(f"  Failed flights:")
        for err in errors[:20]:
            logger.info(f"    {err['flight']} {err['date']} ({err['route']})")
        if len(errors) > 20:
            logger.info(f"    ... and {len(errors) - 20} more")

    # Show best bets from this run
    best = sorted(
        [f for f in all_flights if f.polaris_delta >= 3 and not f.departed],
        key=lambda f: f.polaris_delta, reverse=True,
    )
    if best:
        logger.info("")
        logger.info(f"  BEST BETS (Polaris delta >= 3):")
        for f in best[:15]:
            logger.info(
                f"    {f.route:<9} UA{f.flight_number.replace('UA',''):<5} {f.flight_date}  "
                f"J: {f.polaris_available}/{f.polaris_capacity} delta:{f.polaris_delta:+d}  "
                f"{f.aircraft_type}"
            )

    logger.info("=" * 70)

    return all_flights


def get_all_flights_from_latest(data_path: str = "data/latest.json") -> List[FlightData]:
    """Load all flights from latest.json and return as FlightData objects."""
    latest = load_latest_data(data_path)
    latest = prune_departed(latest)
    flights = []

    # Fields that were removed/renamed — strip them from old data
    _deprecated_fields = {"upgrade_list_cleared", "upgrade_list_waiting", "polaris_standby_total",
                          "premium_plus_standby_total", "economy_standby_total",
                          "polaris_upgrade_list", "polaris_sa_standby",
                          "premium_plus_upgrade_list", "premium_plus_sa_standby",
                          "economy_upgrade_list", "economy_sa_standby"}

    for entry in latest.get("flights", {}).values():
        fd = entry.get("flight_data", {})
        # Strip deprecated fields so FlightData(**fd) doesn't explode
        cleaned = {k: v for k, v in fd.items() if k not in _deprecated_fields}
        try:
            flights.append(FlightData(**cleaned))
        except Exception as e:
            logger.warning(f"Skipping malformed flight entry: {e}")

    return flights
