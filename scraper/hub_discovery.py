"""Discover all UA-operated departures from an airport on a given date.

Uses Playwright to navigate to United's airport departures page and intercept
API responses. Filters to UA-operated only (excludes codeshares).

If URL-based discovery fails, falls back to a curated list of known UA
international/long-haul routes from major hubs.
"""

import asyncio
import logging
import random
from datetime import datetime
from typing import Dict, List

from .browser import BrowserManager

logger = logging.getLogger(__name__)

DISCOVERY_MAX_RETRIES = 2
DISCOVERY_TIMEOUT = 60000  # 60s per URL attempt

# Known UA international/long-haul routes from major hubs.
# Used as fallback when URL-based discovery fails.
KNOWN_UA_ROUTES = {
    "LAX": {
        "europe": ["LHR"],
        "asia_pacific": ["NRT", "HND", "TPE", "PVG", "ICN", "SYD", "MEL"],
        "east_coast": ["EWR", "IAD"],
        "domestic_hubs": ["ORD", "IAH", "DEN", "SFO"],
    },
    "EWR": {
        "europe": ["LHR", "CDG", "FRA", "MUC", "ZRH", "BCN", "LIS", "FCO", "ATH", "DUB", "EDI", "MAN", "BRU"],
        "asia": ["DEL", "BOM", "NRT", "PEK"],
        "middle_east": ["TLV"],
    },
    "SFO": {
        "europe": ["LHR", "CDG", "FRA", "MUC"],
        "asia": ["NRT", "HND", "KIX", "ICN", "SIN", "TPE", "PVG"],
        "oceania": ["SYD", "MEL"],
        "middle_east": ["TLV"],
    },
    "ORD": {
        "europe": ["LHR", "FRA", "MUC", "CDG", "FCO", "ZRH", "DUB"],
        "asia": ["NRT", "HND", "ICN", "PEK", "PVG", "DEL"],
        "middle_east": ["TLV"],
    },
    "IAD": {
        "europe": ["LHR", "FRA", "CDG", "ZRH"],
        "asia": ["NRT"],
        "middle_east": ["TLV"],
        "africa": ["ACC"],
    },
    "IAH": {
        "europe": ["LHR", "FRA", "MUC"],
        "asia": ["NRT"],
        "latin_america": ["CUN", "LIM", "BOG", "GRU", "SCL", "EZE"],
    },
    "DEN": {
        "europe": ["LHR", "FRA", "MUC"],
        "asia": ["NRT"],
    },
}

# URL patterns to try for airport departures (United changes these)
DEPARTURE_URL_PATTERNS = [
    "https://www.united.com/en/us/flightstatus/results/{date}/{airport}/departures",
    "https://www.united.com/en/us/flightstatus/results/airport/{date}/{airport}/departures",
    "https://www.united.com/en/us/flightstatus/results/airport/{airport}/{date}",
]


def _parse_departures(api_data, airport: str, date_str: str) -> List[Dict]:
    """Parse API response into a list of UA-operated flights.

    Handles multiple response formats from United's APIs.
    """
    flights = []
    seen = set()

    # Convert date to API format (MM/DD/YYYY)
    parts = date_str.split('-')
    target_date_api = f"{parts[1]}/{parts[2]}/{parts[0]}"

    # Normalize to list of items
    if isinstance(api_data, list):
        items = api_data
    elif isinstance(api_data, dict):
        # Try various wrapper keys
        for key in ['flights', 'data', 'FlightStatusLegs', 'flightStatusLegs', 'Flights']:
            if key in api_data and isinstance(api_data[key], list):
                items = api_data[key]
                break
        else:
            items = [api_data]
    else:
        return []

    for flight_obj in items:
        # Format 1: FlightLegs > OperationalFlightSegments (route search format)
        if 'FlightLegs' in flight_obj:
            for leg in flight_obj['FlightLegs']:
                for segment in leg.get('OperationalFlightSegments', []):
                    _extract_segment(segment, airport, target_date_api, flights, seen)

        # Format 2: OperationalFlightSegments directly
        elif 'OperationalFlightSegments' in flight_obj:
            for segment in flight_obj['OperationalFlightSegments']:
                _extract_segment(segment, airport, target_date_api, flights, seen)

        # Format 3: Flat flight object
        elif any(k in flight_obj for k in ['FlightNumber', 'flightNumber', 'FlightStatusSegments']):
            # Airport departures format
            segments = flight_obj.get('FlightStatusSegments', [flight_obj])
            for segment in (segments if isinstance(segments, list) else [segments]):
                _extract_flat(segment, airport, flights, seen)

    return sorted(flights, key=lambda f: str(f.get('departure_time', '')))


def _extract_segment(segment: Dict, airport: str, target_date_api: str,
                     flights: List[Dict], seen: set):
    """Extract flight info from an OperationalFlightSegments-style object."""
    operating_airline = segment.get('OperatingAirlineCode', '')
    flight_num = segment.get('FlightNumber')
    dept_airport = segment.get('DepartureAirport', {}).get('IATACode', '')
    arr_airport = segment.get('ArrivalAirport', {}).get('IATACode', '')
    arr_name = segment.get('ArrivalAirport', {}).get('Name', arr_airport)
    dept_time = segment.get('ScheduledDepartureTime', segment.get('DepartureDateTime', ''))
    arr_time = segment.get('ScheduledArrivalTime', segment.get('ArrivalDateTime', ''))
    equipment = segment.get('Equipment', {}).get('Model', {}).get('Description', '')
    dept_datetime = segment.get('DepartureDateTime', '')

    dept_date = dept_datetime.split(' ')[0] if ' ' in dept_datetime else dept_datetime[:10]

    if (operating_airline == 'UA'
            and flight_num
            and dept_airport == airport
            and (not target_date_api or dept_date == target_date_api)):
        dedup_key = f"{flight_num}-{arr_airport}"
        if dedup_key not in seen:
            seen.add(dedup_key)
            if ' ' in dept_time:
                dept_time = dept_time.split(' ')[-1][:5]
            if ' ' in arr_time:
                arr_time = arr_time.split(' ')[-1][:5]
            flights.append({
                'flight_number': int(flight_num),
                'destination': arr_airport,
                'destination_name': arr_name,
                'departure_time': dept_time,
                'arrival_time': arr_time,
                'aircraft_type': equipment,
                'operating_airline': 'UA',
            })


def _extract_flat(segment: Dict, airport: str, flights: List[Dict], seen: set):
    """Extract from a flat flight status object."""
    flight_num = segment.get('FlightNumber', segment.get('flightNumber', ''))
    operating = segment.get('OperatingCarrier', segment.get('OperatingAirlineCode',
                segment.get('operatingCarrier', '')))
    # Normalize operating carrier
    if isinstance(operating, dict):
        operating = operating.get('Code', operating.get('FlightDesignator', ''))[:2]

    dept = segment.get('DepartureAirport', segment.get('Origin', ''))
    if isinstance(dept, dict):
        dept = dept.get('IATACode', dept.get('Code', ''))

    arr = segment.get('ArrivalAirport', segment.get('Destination', ''))
    arr_name = arr
    if isinstance(arr, dict):
        arr_name = arr.get('Name', arr.get('City', ''))
        arr = arr.get('IATACode', arr.get('Code', ''))

    if operating == 'UA' and flight_num and dept == airport:
        dedup_key = f"{flight_num}-{arr}"
        if dedup_key not in seen:
            seen.add(dedup_key)
            flights.append({
                'flight_number': int(flight_num) if str(flight_num).isdigit() else flight_num,
                'destination': arr,
                'destination_name': arr_name if arr_name != arr else arr,
                'departure_time': segment.get('ScheduledDepartureTime',
                                  segment.get('scheduledDepartureTime', '')),
                'arrival_time': segment.get('ScheduledArrivalTime',
                                segment.get('scheduledArrivalTime', '')),
                'aircraft_type': segment.get('Equipment', segment.get('equipment', '')),
                'operating_airline': 'UA',
            })


def summarize_destinations(flights: List[Dict]) -> List[Dict]:
    """Group discovered flights by destination."""
    by_dest = {}
    for f in flights:
        dest = f['destination']
        if dest not in by_dest:
            by_dest[dest] = {
                'destination': dest,
                'destination_name': f.get('destination_name', dest),
                'flights': [],
            }
        by_dest[dest]['flights'].append(f)

    result = []
    for dest, info in by_dest.items():
        info['flight_count'] = len(info['flights'])
        result.append(info)

    return sorted(result, key=lambda d: d['flight_count'], reverse=True)


def get_known_routes(airport: str) -> List[Dict]:
    """Get curated list of known UA routes from an airport.

    Returns list of dicts with destination, destination_name, region.
    """
    airport = airport.upper()
    known = KNOWN_UA_ROUTES.get(airport, {})

    routes = []
    for region, destinations in known.items():
        for dest in destinations:
            routes.append({
                'destination': dest,
                'destination_name': dest,
                'region': region,
                'flight_count': 0,  # Unknown until discovered
            })
    return routes


async def discover_hub_departures(
    browser: BrowserManager,
    airport: str,
    date: datetime,
) -> List[Dict]:
    """Discover all UA-operated departures from an airport.

    Tries multiple URL patterns for United's airport departures page.
    Captures ALL JSON responses for debugging.

    Returns list of flight dicts. Use summarize_destinations() to group.
    """
    date_str = date.strftime("%Y-%m-%d")
    airport = airport.upper()

    for url_pattern in DEPARTURE_URL_PATTERNS:
        url = url_pattern.format(date=date_str, airport=airport)
        logger.info(f"  {airport} | trying URL: {url}")

        for attempt in range(DISCOVERY_MAX_RETRIES + 1):
            captured_responses = []

            async def handle_response(response):
                """Capture ALL JSON responses to find the right one."""
                try:
                    content_type = response.headers.get('content-type', '')
                    if 'json' in content_type or 'javascript' in content_type:
                        resp_url = response.url
                        data = await response.json()
                        captured_responses.append({
                            'url': resp_url,
                            'data': data,
                        })
                except Exception:
                    pass

            page = await browser.get_page()
            page.on('response', handle_response)

            try:
                if attempt > 0:
                    logger.info(f"  {airport} | {date_str} — retry {attempt}")

                await browser.navigate(url, timeout=DISCOVERY_TIMEOUT)
                await asyncio.sleep(8)

                # Log all captured API URLs for debugging
                if captured_responses:
                    api_urls = [r['url'][:120] for r in captured_responses]
                    logger.info(f"  {airport} | captured {len(captured_responses)} JSON responses:")
                    for api_url in api_urls[:10]:
                        logger.info(f"    → {api_url}")

                # Try to parse flights from all captured responses
                all_flights = []
                for resp in captured_responses:
                    flights = _parse_departures(resp['data'], airport, date_str)
                    if flights:
                        logger.info(f"  {airport} | found {len(flights)} flights from: {resp['url'][:100]}")
                        all_flights.extend(flights)

                if all_flights:
                    # Deduplicate
                    seen = set()
                    unique = []
                    for f in all_flights:
                        key = f"{f['flight_number']}-{f['destination']}"
                        if key not in seen:
                            seen.add(key)
                            unique.append(f)

                    destinations = summarize_destinations(unique)
                    dest_codes = [d['destination'] for d in destinations]
                    logger.info(
                        f"  {airport} | {date_str} — found {len(unique)} UA flights "
                        f"to {len(destinations)} destinations: {', '.join(dest_codes)}"
                    )
                    return unique

                logger.warning(
                    f"  {airport} | {date_str} — no UA flights parsed from {len(captured_responses)} responses"
                )

            except Exception as e:
                error_msg = str(e)
                if 'Timeout' in error_msg:
                    logger.warning(f"  {airport} | timeout on {url}")
                else:
                    logger.warning(f"  {airport} | error: {error_msg[:100]}")

                if attempt < DISCOVERY_MAX_RETRIES:
                    browser._page = None

            finally:
                try:
                    page.remove_listener('response', handle_response)
                except Exception:
                    pass

            if attempt < DISCOVERY_MAX_RETRIES:
                backoff = (2 ** attempt) * 3 + random.uniform(0, 3)
                await asyncio.sleep(backoff)

        # Try next URL pattern
        logger.info(f"  {airport} | URL pattern failed, trying next...")

    logger.error(f"  {airport} | {date_str} — all URL patterns failed")
    return []
