"""Scrape individual flight data from United's upgradeListExtended API."""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional

from .browser import BrowserManager
from .models import FlightData

logger = logging.getLogger(__name__)


def parse_flight_data(api_response: Dict, route: str) -> Optional[FlightData]:
    """Parse upgradeListExtended API response into FlightData."""
    try:
        segment = api_response['segment']
        pbts = api_response['pbts']

        flight_date = datetime.strptime(segment['flightDate'], "%Y%m%d")

        # Get cabin data (handle 2 or 3 cabin aircraft)
        front = pbts[0] if len(pbts) > 0 else {}
        middle = pbts[1] if len(pbts) > 1 else {}
        rear = pbts[2] if len(pbts) > 2 else pbts[1] if len(pbts) == 2 else {}

        # Calculate available seats
        polaris_capacity = front.get('capacity', 0)
        polaris_booked = front.get('booked', 0)
        polaris_available = polaris_capacity - polaris_booked

        premium_capacity = middle.get('capacity', 0)
        premium_booked = middle.get('booked', 0)
        premium_available = premium_capacity - premium_booked

        economy_capacity = rear.get('capacity', 0)
        economy_booked = rear.get('booked', 0)
        economy_available = economy_capacity - economy_booked

        # Count standbys by cabin, split by clearanceType
        front_sb = api_response.get('front', {}).get('standby', [])
        polaris_standby = len(front_sb)
        polaris_upgrade_count = sum(1 for p in front_sb if p.get('clearanceType') == 'Upgrade')
        polaris_sa_count = sum(1 for p in front_sb if p.get('clearanceType') == 'Standby')
        polaris_cleared = len(api_response.get('front', {}).get('cleared', []))

        middle_sb = api_response.get('middle', {}).get('standby', [])
        premium_standby = len(middle_sb)
        premium_upgrade_count = sum(1 for p in middle_sb if p.get('clearanceType') == 'Upgrade')
        premium_sa_count = sum(1 for p in middle_sb if p.get('clearanceType') == 'Standby')
        premium_cleared = len(api_response.get('middle', {}).get('cleared', []))

        rear_sb = api_response.get('rear', {}).get('standby', [])
        economy_standby = len(rear_sb)
        economy_upgrade_count = sum(1 for p in rear_sb if p.get('clearanceType') == 'Upgrade')
        economy_sa_count = sum(1 for p in rear_sb if p.get('clearanceType') == 'Standby')
        economy_cleared = len(api_response.get('rear', {}).get('cleared', []))

        # Calculate deltas (available - total standbys)
        polaris_delta = polaris_available - polaris_standby
        premium_delta = premium_available - premium_standby
        economy_delta = economy_available - economy_standby

        return FlightData(
            flight_number=f"UA{segment['flightNumber']}",
            flight_date=flight_date.strftime("%Y-%m-%d"),
            captured_at=datetime.utcnow().isoformat() + "Z",
            day_of_week=flight_date.strftime("%A"),

            departure_airport=segment['departureAirportCode'],
            departure_airport_name=segment['departureAirportName'],
            departure_time=segment['scheduledDepartureTime'],
            arrival_airport=segment['arrivalAirportCode'],
            arrival_airport_name=segment['arrivalAirportName'],
            arrival_time=segment['scheduledArrivalTime'],

            aircraft_type=segment['equipmentDescriptionLong'],
            aircraft_registration=segment.get('ship', 'Unknown'),

            departed=segment.get('departed', False),

            polaris_capacity=polaris_capacity,
            polaris_booked=polaris_booked,
            polaris_available=polaris_available,
            polaris_standby=polaris_standby,
            polaris_delta=polaris_delta,
            polaris_upgrade_count=polaris_upgrade_count,
            polaris_sa_count=polaris_sa_count,
            polaris_cleared=polaris_cleared,
            polaris_revenue_standby=front.get('revenueStandby', 0),
            polaris_sa=front.get('sa', 0),
            polaris_ps=front.get('ps', 0),

            premium_plus_capacity=premium_capacity,
            premium_plus_booked=premium_booked,
            premium_plus_available=premium_available,
            premium_plus_standby=premium_standby,
            premium_plus_delta=premium_delta,
            premium_plus_upgrade_count=premium_upgrade_count,
            premium_plus_sa_count=premium_sa_count,
            premium_plus_cleared=premium_cleared,

            economy_capacity=economy_capacity,
            economy_booked=economy_booked,
            economy_available=economy_available,
            economy_standby=economy_standby,
            economy_delta=economy_delta,
            economy_upgrade_count=economy_upgrade_count,
            economy_sa_count=economy_sa_count,
            economy_cleared=economy_cleared,

            route=route,
            api_response_time_ms=api_response.get('executionTimeInMilliseconds', 0)
        )

    except Exception as e:
        logger.error(f"Error parsing flight data: {e}")
        return None


async def scrape_flight(
    browser: BrowserManager,
    flight_number: int,
    flight_date: datetime,
    origin: str,
    destination: str,
) -> Optional[FlightData]:
    """Scrape a single flight's availability data.

    Returns FlightData on success, None on failure.
    """
    date_str = flight_date.strftime("%Y-%m-%d")
    route = f"{origin}-{destination}"

    logger.info(f"Scraping UA{flight_number} on {date_str} ({route})")

    api_data = None

    async def handle_response(response):
        nonlocal api_data
        if 'upgradeListExtended' in response.url:
            try:
                api_data = await response.json()
            except Exception as e:
                logger.error(f"Failed to parse API response: {e}")

    # Attach listener before navigation
    page = await browser.get_page()
    page.on('response', handle_response)

    try:
        url = f"https://www.united.com/en/us/flightstatus/details/{flight_number}/{date_str}/{origin}/{destination}/UA#upgrades"
        await browser.navigate(url, timeout=60000)

        # Wait for API response
        await asyncio.sleep(4)

        if api_data:
            flight_data = parse_flight_data(api_data, route)
            if flight_data:
                logger.info(
                    f"UA{flight_number}: "
                    f"J={flight_data.polaris_available}/{flight_data.polaris_capacity} "
                    f"(UG:{flight_data.polaris_upgrade_count} SA:{flight_data.polaris_sa_count} delta:{flight_data.polaris_delta}) "
                    f"PP={flight_data.premium_plus_available}/{flight_data.premium_plus_capacity} "
                    f"Y={flight_data.economy_available}/{flight_data.economy_capacity}"
                )
                return flight_data
            else:
                logger.warning(f"Failed to parse data for UA{flight_number}")
        else:
            logger.warning(f"No API data captured for UA{flight_number}")

    except Exception as e:
        logger.error(f"Error scraping UA{flight_number}: {e}")

    finally:
        page.remove_listener('response', handle_response)

    return None
