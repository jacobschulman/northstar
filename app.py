import streamlit as st
import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import deque

# ─── Custom log handler that captures messages for the UI ───
class StreamlitLogHandler(logging.Handler):
    def __init__(self, maxlen=300):
        super().__init__()
        self.records = deque(maxlen=maxlen)

    def emit(self, record):
        self.records.append(self.format(record))

    def get_logs(self) -> str:
        return "\n".join(self.records)

    def clear(self):
        self.records.clear()


log_handler = StreamlitLogHandler()
log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper.log'),
        logging.StreamHandler(sys.stderr),
        log_handler,
    ]
)
logger = logging.getLogger(__name__)

from scraper.browser import BrowserManager
from scraper.hub_discovery import KNOWN_UA_ROUTES
from scraper.route_discovery import auto_discover_flights
from scraper.flight_scraper import scrape_flight
from scraper.rate_limiter import AdaptiveRateLimiter
from scraper.models import FlightData
from scraper.main import load_latest_data, save_latest_data

st.set_page_config(
    page_title="Northstar — United Availability",
    page_icon="✈️",
    layout="wide"
)

st.markdown("""
<style>
    :root {
        --united-blue: #0E3B7C;
        --united-light: #1E5BA8;
        --united-dark: #001E4E;
    }
    h1 { color: var(--united-blue) !important; font-weight: 700 !important; }
    h2, h3 { color: var(--united-dark) !important; font-weight: 600 !important; }
    .subtitle { color: #666; font-size: 0.95rem; margin-bottom: 1rem; }
    .stButton>button {
        background-color: var(--united-blue) !important;
        color: white !important;
        font-weight: 600 !important;
        border: none !important;
        padding: 0.75rem 2rem !important;
        border-radius: 4px !important;
    }
    .stButton>button:hover { background-color: var(--united-light) !important; }
</style>
""", unsafe_allow_html=True)

st.title("✈️ Northstar")
st.markdown('<p class="subtitle">United Airlines seat availability — Polaris business class monitor</p>', unsafe_allow_html=True)


# ─── Sidebar ───
with st.sidebar:
    st.markdown("### Settings")
    show_browser = st.checkbox(
        "Show browser window",
        value=False,
        help="Open visible browser for debugging"
    )
    headless = not show_browser

    st.markdown("---")
    st.markdown("### How it works")
    st.markdown("""
    1. Pick a hub or enter a city pair
    2. Select destinations + days to check
    3. Northstar discovers flight numbers
       via United's flight status page
    4. Then scrapes each flight for Polaris
       seat availability + standby counts

    **J Delta** = available seats − standbys
    - 🟢 **+3 or more** — good
    - 🟡 **0 to +2** — tight
    - 🔴 **negative** — oversold
    """)

    st.markdown("---")
    latest = load_latest_data()
    total_flights = len(latest.get("flights", {}))
    last_updated = latest.get("last_updated", "Never")
    st.markdown(f"**Cached flights:** {total_flights}")
    st.markdown(f"**Last updated:** {last_updated}")


# ─── Helpers ───
def get_day_label(offset: int) -> str:
    """Human-readable label for a day offset."""
    d = datetime.now().date() + timedelta(days=offset)
    if offset == 0:
        return f"Today ({d.strftime('%a %m/%d')})"
    elif offset == 1:
        return f"Tomorrow ({d.strftime('%a %m/%d')})"
    else:
        return d.strftime('%a %m/%d')


def format_delta(delta: int) -> str:
    if delta >= 3:
        return f"🟢 J{delta:+d}"
    elif delta >= 0:
        return f"🟡 J{delta:+d}"
    else:
        return f"🔴 J{delta:+d}"


def display_results(flights: list[FlightData]):
    """Display results as formatted tables grouped by route."""
    if not flights:
        st.warning("No flight data to display.")
        return

    import pandas as pd

    by_route = {}
    for f in flights:
        route = f.route or f"{f.departure_airport}-{f.arrival_airport}"
        by_route.setdefault(route, []).append(f)

    for route, route_flights in sorted(by_route.items()):
        route_flights.sort(key=lambda f: (f.flight_date, f.departure_time))
        non_departed = [f for f in route_flights if not f.departed]
        best_delta = max((f.polaris_delta for f in non_departed), default=0)
        icon = "🟢" if best_delta >= 3 else "🟡" if best_delta >= 0 else "🔴"
        st.subheader(f"{icon} {route} — {len(route_flights)} flight{'s' if len(route_flights) != 1 else ''}")

        rows = []
        for f in route_flights:
            aircraft_short = (f.aircraft_type
                .replace('Boeing ', '').replace('Airbus ', 'A'))
            rows.append({
                "Date": f.flight_date,
                "Day": f.day_of_week[:3],
                "Flight": f.flight_number,
                "Depart": f.departure_time[:5] if len(f.departure_time) > 5 else f.departure_time,
                "Arrive": f.arrival_time[:5] if len(f.arrival_time) > 5 else f.arrival_time,
                "Aircraft": aircraft_short,
                "J Delta": format_delta(f.polaris_delta),
                "J Avail": f"{f.polaris_available}/{f.polaris_capacity}",
                "J SB": f"{f.polaris_standby} (UG:{f.polaris_upgrade_count} SA:{f.polaris_sa_count})",
                "PP Avail": f"{f.premium_plus_available}/{f.premium_plus_capacity}",
                "Y Avail": f"{f.economy_available}/{f.economy_capacity}",
            })

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def show_log_expander(label="Scraper Log"):
    logs = log_handler.get_logs()
    if logs:
        with st.expander(f"📋 {label}", expanded=True):
            st.code(logs, language="text")


async def run_scrape_routes(
    routes: list[tuple[str, str]],
    dates: list[datetime],
    headless: bool = True,
):
    """Discover flights + scrape availability for routes across multiple dates.

    For each route × date, discovers flight numbers then scrapes each one.
    Reuses a single browser session across all routes and dates.
    """
    browser = BrowserManager(headless=headless, context_ttl=15)
    limiter = AdaptiveRateLimiter(base_min=3, base_max=6)
    latest_data = load_latest_data()
    now = datetime.now(tz=None)
    run_timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    all_flights = []

    total_tasks = len(routes) * len(dates)
    task_num = 0

    await browser.start()

    try:
        for orig, dest in routes:
            route_key = f"{orig}-{dest}"

            for date in dates:
                task_num += 1
                date_str = date.strftime("%Y-%m-%d")
                day_name = date.strftime("%a")

                logger.info(f"[{task_num}/{total_tasks}] Discovering {route_key} on {date_str} ({day_name})...")

                nonstop_flights, _ = await auto_discover_flights(browser, orig, dest, date)

                if not nonstop_flights:
                    logger.warning(f"  {route_key} {date_str}: no UA nonstop flights found")
                    continue

                logger.info(f"  {route_key} {date_str}: found {len(nonstop_flights)} flights, scraping...")

                for flight_num in nonstop_flights:
                    flight_key = f"UA{flight_num}_{date_str}"
                    await limiter.wait()

                    result = await scrape_flight(browser, flight_num, date, orig, dest)

                    if result:
                        all_flights.append(result)
                        limiter.record_success()
                        latest_data.setdefault("flights", {})[flight_key] = {
                            "flight_data": result.to_dict(),
                            "last_scraped": run_timestamp,
                        }
                        logger.info(
                            f"    ✓ UA{flight_num} {date_str}: "
                            f"J {result.polaris_available}/{result.polaris_capacity} "
                            f"(Δ{result.polaris_delta:+d}) | "
                            f"PP {result.premium_plus_available}/{result.premium_plus_capacity} | "
                            f"Y {result.economy_available}/{result.economy_capacity} | "
                            f"{result.aircraft_type}"
                        )
                    else:
                        limiter.record_failure()
                        logger.warning(f"    ✗ UA{flight_num} {date_str}: scrape failed")

        latest_data["last_updated"] = run_timestamp
        save_latest_data(latest_data)

    finally:
        await browser.stop()

    return all_flights


# ─── Tabs ───
tab_hub, tab_citypair = st.tabs(["🔍 Browse Hub Routes", "✈️ City Pair"])


# ─── Tab 1: Hub Routes ───
with tab_hub:
    st.markdown("Pick a hub and select destinations to scrape. "
                "These are known UA-operated Polaris routes (codeshares excluded).")

    col1, col2 = st.columns([1, 3])
    with col1:
        hubs = sorted(KNOWN_UA_ROUTES.keys())
        hub_airport = st.selectbox("Hub", hubs, index=hubs.index("LAX") if "LAX" in hubs else 0)

    with col2:
        st.markdown("**Days to check**")
        day_cols = st.columns(5)
        hub_days = []
        for i in range(5):
            with day_cols[i]:
                checked = i == 1  # Default: tomorrow
                if st.checkbox(get_day_label(i), value=checked, key=f"hub_day_{i}"):
                    hub_days.append(i)

    # Show known routes grouped by region
    known = KNOWN_UA_ROUTES.get(hub_airport, {})
    if known:
        st.markdown(f"### Routes from {hub_airport}")

        selected_dests = []
        for region, destinations in known.items():
            region_label = region.replace("_", " ").title()
            st.markdown(f"**{region_label}**")

            cols = st.columns(min(len(destinations), 6))
            for i, dest in enumerate(destinations):
                with cols[i % len(cols)]:
                    if st.checkbox(dest, key=f"hub_{hub_airport}_{dest}"):
                        selected_dests.append(dest)

        if selected_dests and hub_days:
            route_list = ', '.join(f'{hub_airport}-{d}' for d in selected_dests)
            day_list = ', '.join(get_day_label(d) for d in hub_days)
            st.markdown(f"**Selected:** {route_list} | **Days:** {day_list}")

            scrape_btn = st.button(
                f"🚀 Scrape {len(selected_dests)} route{'s' if len(selected_dests) != 1 else ''} × {len(hub_days)} day{'s' if len(hub_days) != 1 else ''}",
                key="hub_scrape",
                use_container_width=True
            )

            if scrape_btn:
                routes = [(hub_airport, d) for d in selected_dests]
                dates = [datetime.combine(datetime.now().date() + timedelta(days=d), datetime.min.time())
                         for d in hub_days]
                log_handler.clear()

                with st.status(
                    f"Scraping {len(routes)} routes × {len(dates)} days from {hub_airport}...",
                    expanded=True
                ) as status_widget:
                    st.write(f"Routes: {route_list}")
                    st.write(f"Days: {day_list}")
                    st.write(f"Total: {len(routes) * len(dates)} route-days. ~30s per route-day. Watch the log below.")

                    try:
                        results = asyncio.run(
                            run_scrape_routes(routes, dates, headless=headless)
                        )
                        if results:
                            status_widget.update(
                                label=f"Done! Scraped {len(results)} flights.",
                                state="complete"
                            )
                            st.session_state['hub_results'] = results
                        else:
                            status_widget.update(label="No data captured", state="error")
                    except Exception as e:
                        status_widget.update(label=f"Error: {e}", state="error")
                        st.exception(e)

                show_log_expander()

        elif selected_dests and not hub_days:
            st.warning("Select at least one day to check.")

        if 'hub_results' in st.session_state:
            st.markdown("---")
            st.markdown("### Results")
            display_results(st.session_state['hub_results'])
    else:
        st.info(f"No curated routes for {hub_airport} yet. Use the City Pair tab instead.")


# ─── Tab 2: City Pair ───
with tab_citypair:
    st.markdown("Enter any origin and destination — Northstar will discover UA flights and scrape availability.")

    col1, col2 = st.columns([1, 1])
    with col1:
        cp_origin = st.text_input("Origin", value="LAX", max_chars=3, key="cp_origin").upper()
    with col2:
        cp_dest = st.text_input("Destination", value="LHR", max_chars=3, key="cp_dest").upper()

    st.markdown("**Days to check**")
    cp_day_cols = st.columns(5)
    cp_days = []
    for i in range(5):
        with cp_day_cols[i]:
            checked = i == 1  # Default: tomorrow
            if st.checkbox(get_day_label(i), value=checked, key=f"cp_day_{i}"):
                cp_days.append(i)

    cp_btn = st.button("🚀 Scrape Route", key="cp_scrape", use_container_width=True)

    if cp_btn:
        if not cp_origin or not cp_dest or len(cp_origin) != 3 or len(cp_dest) != 3:
            st.error("Please enter valid 3-letter airport codes.")
        elif not cp_days:
            st.error("Select at least one day to check.")
        else:
            routes = [(cp_origin, cp_dest)]
            dates = [datetime.combine(datetime.now().date() + timedelta(days=d), datetime.min.time())
                     for d in cp_days]
            day_list = ', '.join(get_day_label(d) for d in cp_days)
            log_handler.clear()

            with st.status(
                f"Scraping {cp_origin}-{cp_dest} across {len(dates)} day{'s' if len(dates) != 1 else ''}...",
                expanded=True
            ) as status_widget:
                st.write(f"Route: {cp_origin} → {cp_dest}")
                st.write(f"Days: {day_list}")

                try:
                    results = asyncio.run(
                        run_scrape_routes(routes, dates, headless=headless)
                    )
                    if results:
                        status_widget.update(
                            label=f"Scraped {len(results)} flights for {cp_origin}-{cp_dest}!",
                            state="complete"
                        )
                        st.session_state['cp_results'] = results
                    else:
                        status_widget.update(label=f"No data for {cp_origin}-{cp_dest}", state="error")
                        st.warning(
                            f"No flight data captured. This could mean no UA nonstop flights "
                            f"on this route, or the browser was blocked.\n\n"
                            f"Try enabling **Show browser window** in the sidebar."
                        )
                except Exception as e:
                    status_widget.update(label=f"Error: {e}", state="error")
                    st.exception(e)

            show_log_expander()

    if 'cp_results' in st.session_state:
        st.markdown("---")
        display_results(st.session_state['cp_results'])
