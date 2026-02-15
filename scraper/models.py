"""Data models for United Airlines flight availability."""

from dataclasses import dataclass, asdict
from typing import List, Dict, Optional


@dataclass
class FlightData:
    """Structured flight data from United's upgradeListExtended API."""
    flight_number: str
    flight_date: str
    captured_at: str
    day_of_week: str

    # Route info
    departure_airport: str
    departure_airport_name: str
    departure_time: str
    arrival_airport: str
    arrival_airport_name: str
    arrival_time: str

    # Aircraft
    aircraft_type: str
    aircraft_registration: str

    # Flight status
    departed: bool

    # Connection info (None for nonstop flights)
    is_connection: bool = False
    connection_route: Optional[str] = None
    segments: Optional[List[Dict]] = None

    # ── Polaris Business (Front cabin) ──
    polaris_capacity: int = 0
    polaris_booked: int = 0
    polaris_available: int = 0         # capacity - booked
    polaris_standby: int = 0           # Total on standby list (UG + SA)
    polaris_delta: int = 0             # available - standby (the key number)

    # Standby breakdown (stored for investigation, not displayed in main reports)
    polaris_upgrade_count: int = 0     # clearanceType: "Upgrade" — confirmed pax wanting upgrade
    polaris_sa_count: int = 0          # clearanceType: "Standby" — non-rev / SA passengers
    polaris_cleared: int = 0           # Already upgraded/cleared (from front.cleared)

    # pbts extras for Polaris
    polaris_revenue_standby: int = 0   # From pbts.revenueStandby
    polaris_sa: int = 0                # From pbts.sa (space-available count)
    polaris_ps: int = 0                # From pbts.ps (positive space)

    # ── Premium Plus (Middle cabin) ──
    premium_plus_capacity: int = 0
    premium_plus_booked: int = 0
    premium_plus_available: int = 0
    premium_plus_standby: int = 0
    premium_plus_delta: int = 0
    premium_plus_upgrade_count: int = 0
    premium_plus_sa_count: int = 0
    premium_plus_cleared: int = 0

    # ── Economy (Rear cabin) ──
    economy_capacity: int = 0
    economy_booked: int = 0
    economy_available: int = 0
    economy_standby: int = 0
    economy_delta: int = 0
    economy_upgrade_count: int = 0
    economy_sa_count: int = 0
    economy_cleared: int = 0

    # Metadata
    route: str = ""
    api_response_time_ms: float = 0

    def to_dict(self) -> Dict:
        return asdict(self)
