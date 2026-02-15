"""Generate static HTML reports from flight data."""

import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List

from jinja2 import Environment, FileSystemLoader

from scraper.models import FlightData


def generate_html_report(
    flights: List[FlightData],
    output_dir: str = "docs",
    config_path: str = "config/routes.json",
):
    """Generate a static HTML report site.

    Args:
        flights: List of FlightData objects to report on
        output_dir: Directory to write HTML files to
        config_path: Path to routes config for region lookup
    """
    template_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now().strftime("%Y-%m-%d %I:%M %p ET")

    # Load route config for region lookup
    route_region_map = {}
    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file) as f:
            config = json.load(f)
        for r in config.get("routes", []):
            key = f"{r['origin']}-{r['destination']}"
            route_region_map[key] = r.get("region", "other")

    # Filter out departed flights
    active_flights = [f for f in flights if not f.departed]

    # Get unique hubs and regions
    hubs = sorted(set(f.departure_airport for f in active_flights))
    all_regions = sorted(set(route_region_map.values())) if route_region_map else []
    region_display = {r: r.replace("_", " ").title() for r in all_regions}

    # Group by route (for route detail pages)
    routes = {}
    for f in active_flights:
        routes.setdefault(f.route, []).append(f)

    # --- Day-based grouping ---
    today = date.today()
    day_dates = [today + timedelta(days=i) for i in range(3)]

    day_labels = []
    for i, d in enumerate(day_dates):
        if i == 0:
            label = "Today"
        elif i == 1:
            label = "Tomorrow"
        else:
            label = d.strftime("%A")
        day_labels.append({
            "index": i,
            "label": label,
            "date": d.isoformat(),
            "display": d.strftime("%a %b %d"),
        })

    # Build per-day card data
    days_data = []
    for day_idx, day_date in enumerate(day_dates):
        date_str = day_date.isoformat()
        day_flights = [f for f in active_flights if f.flight_date == date_str]

        # Group by route within this day
        route_groups = {}
        for f in day_flights:
            route_groups.setdefault(f.route, []).append(f)

        route_cards = []
        best_bet_count = 0

        for route_key, rflights in route_groups.items():
            # Sort flights by delta descending
            sorted_rflights = sorted(rflights, key=lambda f: f.polaris_delta, reverse=True)
            best_delta = sorted_rflights[0].polaris_delta

            if best_delta >= 3:
                best_bet_count += 1

            hub = sorted_rflights[0].departure_airport
            region = route_region_map.get(route_key, "other")
            origin = route_key.split("-")[0]
            destination = route_key.split("-")[1]

            # Build per-flight rows
            flight_rows = []
            for f in sorted_rflights:
                dep_time = f.departure_time.split(" ", 1)[1] if " " in f.departure_time else f.departure_time
                aircraft = f.aircraft_type
                for prefix in ["Boeing ", "Airbus "]:
                    aircraft = aircraft.replace(prefix, "")

                flight_rows.append({
                    "flight_number": f.flight_number,
                    "departure_time": dep_time,
                    "aircraft": aircraft,
                    "polaris_delta": f.polaris_delta,
                    "polaris_available": f.polaris_available,
                    "polaris_capacity": f.polaris_capacity,
                    "polaris_standby": f.polaris_standby,
                    "delta_class": (
                        "positive" if f.polaris_delta >= 3
                        else ("neutral" if f.polaris_delta >= 0 else "negative")
                    ),
                })

            route_cards.append({
                "route": route_key,
                "origin": origin,
                "destination": destination,
                "hub": hub,
                "region": region,
                "best_delta": best_delta,
                "flight_count": len(rflights),
                "flights": flight_rows,
                "delta_class": (
                    "positive" if best_delta >= 3
                    else ("neutral" if best_delta >= 0 else "negative")
                ),
            })

        route_cards.sort(key=lambda c: c["best_delta"], reverse=True)

        days_data.append({
            "index": day_idx,
            "label": day_labels[day_idx]["label"],
            "date": date_str,
            "display": day_labels[day_idx]["display"],
            "route_cards": route_cards,
            "best_bet_count": best_bet_count,
            "total_flights": len(day_flights),
            "total_routes": len(route_groups),
        })

    # Summary stats
    summary = {
        "total_routes": len(routes),
        "total_flights": len(active_flights),
        "total_best_bets": sum(d["best_bet_count"] for d in days_data),
        "days": [{"label": d["label"], "best_bets": d["best_bet_count"]} for d in days_data],
    }

    # --- Render index page ---
    index_template = env.get_template("index.html")
    index_html = index_template.render(
        days=days_data,
        summary=summary,
        hubs=hubs,
        regions=all_regions,
        region_display=region_display,
        generated_at=generated_at,
    )
    (output / "index.html").write_text(index_html)

    # Copy CSS
    shutil.copy(str(template_dir / "style.css"), str(output / "style.css"))

    # --- Render per-route pages ---
    route_dir = output / "routes"
    route_dir.mkdir(parents=True, exist_ok=True)

    route_template = env.get_template("route.html")
    for route_key, route_flights in routes.items():
        sorted_flights = sorted(route_flights, key=lambda f: (f.flight_date, f.departure_time))
        region = route_region_map.get(route_key, "other")

        # Group flights by day for the route detail page
        flights_by_day = []
        for day_idx, day_date in enumerate(day_dates):
            date_str = day_date.isoformat()
            day_flights = [f for f in sorted_flights if f.flight_date == date_str]
            if day_flights:
                flights_by_day.append({
                    "label": day_labels[day_idx]["label"],
                    "display": day_labels[day_idx]["display"],
                    "flights": day_flights,
                })

        origin = route_key.split("-")[0]
        destination = route_key.split("-")[1]

        route_html = route_template.render(
            route=route_key,
            origin=origin,
            destination=destination,
            region=region_display.get(region, region),
            flights=sorted_flights,
            flights_by_day=flights_by_day,
            generated_at=generated_at,
        )
        (route_dir / f"{route_key}.html").write_text(route_html)
