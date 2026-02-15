"""CLI table and JSON output for Northstar reports."""

import json
import sys
from datetime import datetime
from typing import List

from scraper.models import FlightData


# ANSI color codes
class Color:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'


def _use_color() -> bool:
    return sys.stdout.isatty()


def _color(text: str, color: str) -> str:
    if _use_color():
        return f"{color}{text}{Color.RESET}"
    return text


def _delta_color(delta: int, text: str) -> str:
    if delta >= 3:
        return _color(text, Color.GREEN)
    elif delta >= 0:
        return _color(text, Color.YELLOW)
    else:
        return _color(text, Color.RED)


def _format_delta(delta: int) -> str:
    """Format delta as a prominent, color-coded string."""
    if delta > 0:
        text = f"+{delta}"
    else:
        text = str(delta)
    return _delta_color(delta, f"{text:>4}")


def print_json(flights: List[FlightData]):
    """Output all flight data as JSON to stdout."""
    output = {
        "run_timestamp": datetime.utcnow().isoformat() + "Z",
        "total_flights": len(flights),
        "flights": [f.to_dict() for f in flights],
    }
    json.dump(output, sys.stdout, indent=2)
    print()  # trailing newline


def print_report(flights: List[FlightData]):
    """Print a formatted CLI table report."""
    if not flights:
        print("No flight data available.")
        return

    now = datetime.now().strftime("%Y-%m-%d %I:%M %p ET")
    routes_count = len(set(f.route for f in flights))

    # Header
    w = 110
    sep = "=" * w
    thin_sep = "-" * w
    print()
    print(_color(sep, Color.BOLD))
    print(_color(f"  NORTHSTAR — United Seat Availability Report", Color.BOLD))
    print(_color(f"  {routes_count} routes, {len(flights)} flights | {now}", Color.DIM))
    print(_color(sep, Color.BOLD))

    # Best bets: flights with polaris_delta >= 3, sorted by delta descending
    best_bets = sorted(
        [f for f in flights if f.polaris_delta >= 3 and not f.departed],
        key=lambda f: f.polaris_delta,
        reverse=True,
    )

    if best_bets:
        print()
        print(_color(f"  BEST BETS (Polaris delta >= 3)", Color.BOLD))
        print(f"  {thin_sep}")
        _print_header()
        for flight in best_bets[:30]:
            _print_flight_row(flight)

    # All flights by route
    print()
    print(_color(f"  ALL FLIGHTS BY ROUTE", Color.BOLD))
    print(f"  {thin_sep}")

    # Group by route
    routes = {}
    for f in flights:
        routes.setdefault(f.route, []).append(f)

    for route_key in sorted(routes.keys()):
        route_flights = sorted(routes[route_key], key=lambda f: (f.flight_date, f.departure_time))
        print()
        print(_color(f"  {route_key}", Color.BOLD))
        _print_header()
        for flight in route_flights:
            _print_flight_row(flight)

    print()


def _print_header():
    """Print table header row."""
    print(
        f"  {'Route':<9} {'Flight':<8} {'Date':<12} {'Depart':<8}"
        f" {'Aircraft':<14}"
        f"  {_color('J Delta', Color.BOLD):>4}  {'J Avl/Cap':>9} {'J SB':>4}"
        f"  {'PP Avl/Cap':>10} {'PP SB':>5}"
        f"  {'Y Avl/Cap':>9} {'Y SB':>4}"
    )


def _print_flight_row(f: FlightData):
    """Print a single flight row."""
    # Shorten aircraft type
    aircraft = f.aircraft_type
    for prefix in ["Boeing ", "Airbus "]:
        aircraft = aircraft.replace(prefix, "")
    aircraft = aircraft[:13]

    # Format date
    try:
        dt = datetime.strptime(f.flight_date, "%Y-%m-%d")
        date_str = dt.strftime("%b %d %a")
    except ValueError:
        date_str = f.flight_date[:10]

    # Format departure time (truncate to fit)
    depart = f.departure_time
    if len(depart) > 7:
        depart = depart[-8:]  # Take the time portion
    depart = depart[:7]

    j_delta = _format_delta(f.polaris_delta)
    pp_delta_val = f.premium_plus_delta
    y_delta_val = f.economy_delta

    departed = _color(" [D]", Color.DIM) if f.departed else ""

    print(
        f"  {f.route:<9} {f.flight_number:<8} {date_str:<12} {depart:<8}"
        f" {aircraft:<14}"
        f"  {j_delta}  {f.polaris_available:>3}/{f.polaris_capacity:<3}  {f.polaris_standby:>3}"
        f"   {f.premium_plus_available:>3}/{f.premium_plus_capacity:<3}   {f.premium_plus_standby:>3}"
        f"  {f.economy_available:>3}/{f.economy_capacity:<3}  {f.economy_standby:>3}"
        f"{departed}"
    )
