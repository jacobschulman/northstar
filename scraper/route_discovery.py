"""Auto-discover flight numbers for a route on a given date."""

import asyncio
import logging
import random
from datetime import datetime
from typing import List, Dict, Tuple

from .browser import BrowserManager

logger = logging.getLogger(__name__)

DISCOVERY_MAX_RETRIES = 3
DISCOVERY_TIMEOUT = 90000  # 90s — generous for slow connections


def _parse_trip_data(
    trip_data, origin: str, destination: str, date_str: str
) -> Tuple[List[int], List[Dict]]:
    """Parse the trip API response into nonstop flight numbers and connections."""
    flight_numbers = []
    connection_flights = []

    # Convert date to API format (MM/DD/YYYY)
    target_parts = date_str.split('-')
    target_date_api = f"{target_parts[1]}/{target_parts[2]}/{target_parts[0]}"

    if not isinstance(trip_data, list):
        return [], []

    for flight_obj in trip_data:
        if 'FlightLegs' not in flight_obj:
            continue

        for leg in flight_obj['FlightLegs']:
            if 'OperationalFlightSegments' not in leg:
                continue

            segments = leg['OperationalFlightSegments']
            journey_segments = []

            for segment in segments:
                flight_num = segment.get('FlightNumber')
                operating_airline = segment.get('OperatingAirlineCode')
                dept_datetime = segment.get('DepartureDateTime', '')
                dept_airport = segment.get('DepartureAirport', {}).get('IATACode', '')
                arr_airport = segment.get('ArrivalAirport', {}).get('IATACode', '')

                dept_date = dept_datetime.split(' ')[0] if ' ' in dept_datetime else dept_datetime[:10]

                if operating_airline == 'UA' and flight_num and dept_date == target_date_api:
                    journey_segments.append({
                        'flight_num': int(flight_num),
                        'origin': dept_airport,
                        'destination': arr_airport
                    })

            # Classify: nonstop vs connection
            if len(journey_segments) == 1:
                seg = journey_segments[0]
                if seg['origin'] == origin and seg['destination'] == destination:
                    flight_numbers.append(seg['flight_num'])

            elif len(journey_segments) > 1:
                first_origin = journey_segments[0]['origin']
                last_dest = journey_segments[-1]['destination']

                if first_origin == origin and last_dest == destination:
                    connection_flights.append({
                        'segments': journey_segments,
                        'route': ' -> '.join(
                            [s['origin'] for s in journey_segments] + [last_dest]
                        )
                    })

    return sorted(set(flight_numbers)), connection_flights


async def auto_discover_flights(
    browser: BrowserManager,
    origin: str,
    destination: str,
    date: datetime,
) -> Tuple[List[int], List[Dict]]:
    """Auto-discover flight numbers for a route on a specific date.

    Retries up to DISCOVERY_MAX_RETRIES times on failure with exponential backoff.

    Returns:
        (nonstop_flight_numbers, connection_flights) where connection_flights
        contains full route info with segment details.
    """
    date_str = date.strftime("%Y-%m-%d")
    route_key = f"{origin}-{destination}"

    for attempt in range(DISCOVERY_MAX_RETRIES + 1):
        trip_data = None

        async def handle_response(response):
            nonlocal trip_data
            if '/api/flightstatus/trip/' in response.url:
                try:
                    trip_data = await response.json()
                except Exception as e:
                    logger.error(f"Failed to parse trip API: {e}")

        page = await browser.get_page()
        page.on('response', handle_response)

        try:
            overview_url = f"https://www.united.com/en/us/flightstatus/results/route/{date_str}/{origin}/{destination}/UA"

            if attempt > 0:
                logger.info(f"  {route_key} | {date_str} — retry {attempt}/{DISCOVERY_MAX_RETRIES}")

            await browser.navigate(overview_url, timeout=DISCOVERY_TIMEOUT)

            # Wait for API response — give extra time on retries
            wait_time = 5 + (attempt * 3)
            await asyncio.sleep(wait_time)

            if trip_data:
                flight_numbers, connection_flights = _parse_trip_data(
                    trip_data, origin, destination, date_str
                )
                logger.info(
                    f"  {route_key} | {date_str} — found {len(flight_numbers)} nonstop flights: "
                    f"UA{', UA'.join(str(f) for f in flight_numbers)}"
                    if flight_numbers else
                    f"  {route_key} | {date_str} — no nonstop UA flights found"
                )
                return flight_numbers, connection_flights

            # No data captured — retry
            logger.warning(
                f"  {route_key} | {date_str} — no trip data captured"
                f" (attempt {attempt + 1}/{DISCOVERY_MAX_RETRIES + 1})"
            )

        except Exception as e:
            error_msg = str(e)
            if 'Timeout' in error_msg:
                logger.warning(
                    f"  {route_key} | {date_str} — timeout ({DISCOVERY_TIMEOUT}ms)"
                    f" (attempt {attempt + 1}/{DISCOVERY_MAX_RETRIES + 1})"
                )
            else:
                logger.error(
                    f"  {route_key} | {date_str} — discovery error: {error_msg}"
                    f" (attempt {attempt + 1}/{DISCOVERY_MAX_RETRIES + 1})"
                )

            # Force context rotation on failure — get a fresh browser context
            if attempt < DISCOVERY_MAX_RETRIES:
                browser._page = None  # Force rotation on next get_page()

        finally:
            try:
                page.remove_listener('response', handle_response)
            except Exception:
                pass

        # Backoff before retry
        if attempt < DISCOVERY_MAX_RETRIES:
            backoff = (2 ** attempt) * 5 + random.uniform(0, 5)
            logger.info(f"  {route_key} | {date_str} — waiting {backoff:.0f}s before retry")
            await asyncio.sleep(backoff)

    logger.error(f"  {route_key} | {date_str} — discovery FAILED after {DISCOVERY_MAX_RETRIES + 1} attempts")
    return [], []
