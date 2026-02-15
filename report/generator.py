"""Generate static HTML reports from flight data."""

import shutil
from datetime import datetime
from pathlib import Path
from typing import List

from jinja2 import Environment, FileSystemLoader

from scraper.models import FlightData


def generate_html_report(flights: List[FlightData], output_dir: str = "docs"):
    """Generate a static HTML report site.

    Args:
        flights: List of FlightData objects to report on
        output_dir: Directory to write HTML files to
    """
    template_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now().strftime("%Y-%m-%d %I:%M %p ET")

    # Filter out departed flights
    active_flights = [f for f in flights if not f.departed]

    # Best bets: polaris_delta >= 3
    best_bets = sorted(
        [f for f in active_flights if f.polaris_delta >= 3],
        key=lambda f: f.polaris_delta,
        reverse=True,
    )

    # Group by route
    routes = {}
    for f in active_flights:
        routes.setdefault(f.route, []).append(f)

    # Get unique hubs from departure airports
    hubs = sorted(set(f.departure_airport for f in active_flights))

    # Render index page
    index_template = env.get_template("index.html")
    index_html = index_template.render(
        flights=active_flights,
        best_bets=best_bets[:50],
        routes=routes,
        hubs=hubs,
        generated_at=generated_at,
    )
    (output / "index.html").write_text(index_html)

    # Copy CSS
    shutil.copy(str(template_dir / "style.css"), str(output / "style.css"))

    # Render per-route pages
    route_dir = output / "routes"
    route_dir.mkdir(parents=True, exist_ok=True)

    route_template = env.get_template("route.html")
    for route_key, route_flights in routes.items():
        sorted_flights = sorted(route_flights, key=lambda f: (f.flight_date, f.departure_time))
        route_html = route_template.render(
            route=route_key,
            flights=sorted_flights,
            generated_at=generated_at,
        )
        (route_dir / f"{route_key}.html").write_text(route_html)
