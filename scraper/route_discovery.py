"""Auto-discover flight numbers for a route on a given date."""

import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Tuple

from .browser import BrowserManager

logger = logging.getLogger(__name__)


async def auto_discover_flights(
    browser: BrowserManager,
    origin: str,
    destination: str,
    date: datetime,
) -> Tuple[List[int], List[Dict]]:
    """Auto-discover flight numbers for a route on a specific date.

    Returns:
        (nonstop_flight_numbers, connection_flights) where connection_flights
        contains full route info with segment details.
    """
    date_str = date.strftime("%Y-%m-%d")
    logger.info(f"Discovering flights for {origin}-{destination} on {date_str}")

    trip_data = None

    async def handle_response(response):
        nonlocal trip_data
        if '/api/flightstatus/trip/' in response.url:
            try:
                trip_data = await response.json()
            except Exception as e:
                logger.error(f"Failed to parse trip API: {e}")

    # Get page and attach listener
    page = await browser.get_page()
    page.on('response', handle_response)

    try:
        overview_url = f"https://www.united.com/en/us/flightstatus/results/route/{date_str}/{origin}/{destination}/UA"
        await browser.navigate(overview_url, timeout=60000)
        await asyncio.sleep(5)

        if not trip_data:
            logger.warning(f"No trip data captured for {origin}-{destination} on {date_str}")
            return [], []

        flight_numbers = []
        connection_flights = []

        # Convert date to API format (MM/DD/YYYY)
        target_parts = date_str.split('-')
        target_date_api = f"{target_parts[1]}/{target_parts[2]}/{target_parts[0]}"

        if isinstance(trip_data, list):
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

        flight_numbers = sorted(set(flight_numbers))

        logger.info(f"Found {len(flight_numbers)} nonstop flights: {flight_numbers}")
        if connection_flights:
            logger.info(f"Found {len(connection_flights)} connection options")

        return flight_numbers, connection_flights

    except Exception as e:
        logger.error(f"Error during auto-discovery for {origin}-{destination}: {e}")
        return [], []

    finally:
        page.remove_listener('response', handle_response)
