import streamlit as st
import asyncio
import json
import logging
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from collections import deque
from queue import Queue, Empty

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
from scraper.route_discovery import auto_discover_flights
from scraper.flight_scraper import scrape_flight
from scraper.rate_limiter import AdaptiveRateLimiter
from scraper.models import FlightData
from scraper.main import load_latest_data, save_latest_data


HUB_DESTINATIONS_FILE = Path("config/hub_destinations.json")


def load_hub_destinations() -> dict:
    """Load the static list of destinations per hub scraped from united.com
    marketing pages. Regenerate via scripts/fetch_hub_destinations.py."""
    if HUB_DESTINATIONS_FILE.exists():
        return json.loads(HUB_DESTINATIONS_FILE.read_text())
    return {}

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
        value=True,
        help="United blocks headless browsers — leave this on.",
    )
    headless = not show_browser
    if headless:
        st.warning("⚠️ Headless mode is blocked by United. Expect timeouts.")

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
    on_progress=None,
    stop_event: threading.Event | None = None,
):
    """Discover flights + scrape availability for routes across multiple dates.

    For each route × date, discovers flight numbers then scrapes each one.
    Reuses a single browser session across all routes and dates.

    Progress is emitted via both the logger AND an optional on_progress callback
    (called from the scraping thread). A threading.Event can be used to stop
    after the current flight.
    """
    def emit(msg: str, level: str = "info"):
        getattr(logger, level)(msg)
        if on_progress:
            on_progress(msg)

    def should_stop() -> bool:
        return stop_event is not None and stop_event.is_set()

    browser = BrowserManager(headless=headless, context_ttl=15)
    limiter = AdaptiveRateLimiter(base_min=3, base_max=6)
    latest_data = load_latest_data()
    now = datetime.now(tz=None)
    run_timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    all_flights = []

    total_tasks = len(routes) * len(dates)
    task_num = 0

    emit(f"🚀 Starting scrape: {len(routes)} route(s) × {len(dates)} day(s) = {total_tasks} task(s)")
    emit(f"🌐 Launching browser (headless={headless})...")
    await browser.start()

    try:
        for orig, dest in routes:
            if should_stop():
                emit("⛔ Stop requested — aborting.", level="warning")
                break
            route_key = f"{orig}-{dest}"

            for date in dates:
                if should_stop():
                    emit("⛔ Stop requested — aborting.", level="warning")
                    break
                task_num += 1
                date_str = date.strftime("%Y-%m-%d")
                day_name = date.strftime("%a")

                emit(f"[{task_num}/{total_tasks}] 🔎 Discovering {route_key} on {date_str} ({day_name})...")

                nonstop_flights, _ = await auto_discover_flights(browser, orig, dest, date)

                if not nonstop_flights:
                    emit(f"  ⚠️ {route_key} {date_str}: no UA nonstop flights found", level="warning")
                    continue

                emit(f"  ✈️ {route_key} {date_str}: found {len(nonstop_flights)} flight(s), scraping...")

                for flight_num in nonstop_flights:
                    if should_stop():
                        emit("⛔ Stop requested — aborting.", level="warning")
                        break
                    flight_key = f"UA{flight_num}_{date_str}"
                    await limiter.wait()

                    emit(f"    → UA{flight_num} {date_str}: scraping...")
                    result = await scrape_flight(browser, flight_num, date, orig, dest)

                    if result:
                        all_flights.append(result)
                        limiter.record_success()
                        latest_data.setdefault("flights", {})[flight_key] = {
                            "flight_data": result.to_dict(),
                            "last_scraped": run_timestamp,
                        }
                        emit(
                            f"    ✓ UA{flight_num} {date_str}: "
                            f"J {result.polaris_available}/{result.polaris_capacity} "
                            f"(Δ{result.polaris_delta:+d}) | "
                            f"PP {result.premium_plus_available}/{result.premium_plus_capacity} | "
                            f"Y {result.economy_available}/{result.economy_capacity} | "
                            f"{result.aircraft_type}"
                        )
                    else:
                        limiter.record_failure()
                        emit(f"    ✗ UA{flight_num} {date_str}: scrape failed", level="warning")

        latest_data["last_updated"] = run_timestamp
        save_latest_data(latest_data)
        emit(f"💾 Saved {len(all_flights)} flight(s) to latest.json")

    finally:
        await browser.stop()
        emit("👋 Browser shut down")

    return all_flights


# ─── Background scrape state (shared across tabs) ───
def get_scrape_state() -> dict:
    if "scrape" not in st.session_state:
        st.session_state.scrape = {
            "status": "idle",       # idle | running | complete | empty | error
            "log": [],
            "results": None,
            "queue": None,
            "stop_event": None,
            "thread": None,
            "origin": None,         # "hub" or "cp"
        }
    return st.session_state.scrape


def start_scrape_thread(routes, dates, headless, origin: str):
    state = get_scrape_state()

    # Guard: don't start a second job on top of a running one
    if state["status"] == "running":
        return

    state["status"] = "running"
    state["log"] = []
    state["results"] = None
    state["queue"] = Queue()
    state["stop_event"] = threading.Event()
    state["origin"] = origin

    q = state["queue"]
    stop_event = state["stop_event"]

    def worker():
        async def _run():
            results = await run_scrape_routes(
                routes, dates,
                headless=headless,
                on_progress=lambda m: q.put(("LOG", m)),
                stop_event=stop_event,
            )
            q.put(("DONE", results))

        try:
            asyncio.run(_run())
        except Exception as e:
            q.put(("ERROR", f"{type(e).__name__}: {e}"))

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    state["thread"] = t


def drain_scrape_queue():
    state = get_scrape_state()
    q = state.get("queue")
    if q is None:
        return
    while True:
        try:
            kind, payload = q.get_nowait()
        except Empty:
            break
        if kind == "LOG":
            state["log"].append(payload)
        elif kind == "DONE":
            state["results"] = payload
            state["status"] = "complete" if payload else "empty"
            if state["origin"] == "hub":
                st.session_state["hub_results"] = payload or []
            elif state["origin"] == "cp":
                st.session_state["cp_results"] = payload or []
        elif kind == "ERROR":
            state["log"].append(f"❌ ERROR: {payload}")
            state["status"] = "error"


def render_scrape_live() -> bool:
    """Render live scrape status (stop button + log). Returns True if still running."""
    state = get_scrape_state()
    drain_scrape_queue()

    if state["status"] == "idle":
        return False

    running = state["status"] == "running"

    header_col, btn_col = st.columns([4, 1])
    with header_col:
        if running:
            st.info(f"⏳ Scraping… {len(state['log'])} event(s) logged")
        elif state["status"] == "complete":
            st.success(f"✅ Done — {len(state['results'] or [])} flight(s) scraped")
        elif state["status"] == "empty":
            st.warning("No flight data captured.")
        elif state["status"] == "error":
            st.error("❌ Scrape failed — see log below.")

    with btn_col:
        if running:
            if st.button("⛔ Stop", key="scrape_stop_btn", use_container_width=True):
                state["stop_event"].set()
                state["log"].append("⛔ Stop signal sent — finishing current flight...")
        else:
            if st.button("Clear", key="scrape_clear_btn", use_container_width=True):
                state["status"] = "idle"
                state["log"] = []
                st.rerun()

    # Live log — expanded while running, collapsed when done (to keep results prominent)
    log_text = "\n".join(state["log"][-500:]) if state["log"] else "(starting…)"
    log_label = f"📋 Live log ({len(state['log'])} events)"
    with st.expander(log_label, expanded=running):
        st.code(log_text, language="text")

    return running


# ─── Tabs ───
tab_hub, tab_citypair = st.tabs(["🔍 Browse Hub Routes", "✈️ City Pair"])


# ─── Tab 1: Hub Routes ───
with tab_hub:
    hub_data = load_hub_destinations()

    if not hub_data:
        st.warning(
            "No hub destination list found. "
            "Run `python scripts/fetch_hub_destinations.py` "
            "to build `config/hub_destinations.json`."
        )
    else:
        st.markdown(
            "Destinations sourced from each hub's Wikipedia airport page — "
            "full UA route list including seasonal."
        )

        col1, col2 = st.columns([1, 3])
        with col1:
            hubs = sorted(hub_data.keys())
            default_idx = hubs.index("EWR") if "EWR" in hubs else 0
            hub_airport = st.selectbox("Hub", hubs, index=default_idx, key="hub_select")

        with col2:
            st.markdown("**Days to check**")
            day_cols = st.columns(5)
            hub_days = []
            for i in range(5):
                with day_cols[i]:
                    checked = i == 1  # Default: tomorrow
                    if st.checkbox(get_day_label(i), value=checked, key=f"hub_day_{i}"):
                        hub_days.append(i)

        raw_destinations = hub_data[hub_airport].get("destinations", [])
        # Backwards-compat: old schema had list[str]; new schema is list[dict]
        if raw_destinations and isinstance(raw_destinations[0], str):
            raw_destinations = [{"iata": d, "city": d, "country": "?",
                                 "international": True} for d in raw_destinations]

        intl_only = st.toggle(
            "🌍 International only (Polaris routes)",
            value=True,
            key=f"intl_only_{hub_airport}",
            help="Hide domestic routes — Polaris business class is long-haul only.",
        )

        destinations = [d for d in raw_destinations
                        if d.get("international", True)] if intl_only else raw_destinations

        # Group by country for readability when showing international
        intl_count = sum(1 for d in raw_destinations if d.get("international"))
        dom_count = len(raw_destinations) - intl_count
        st.markdown(
            f"### Destinations from {hub_airport} — "
            f"showing {len(destinations)} "
            f"({intl_count} intl + {dom_count} dom total)"
        )

        col_a, col_b = st.columns([1, 1])
        with col_a:
            if st.button("Select all shown", key="hub_select_all", use_container_width=True):
                for d in destinations:
                    st.session_state[f"dest_{hub_airport}_{d['iata']}"] = True
                st.rerun()
        with col_b:
            if st.button("Clear selection", key="hub_clear", use_container_width=True):
                for d in raw_destinations:
                    st.session_state[f"dest_{hub_airport}_{d['iata']}"] = False
                st.rerun()

        selected_dests = []
        cols_per_row = 6
        cols = st.columns(cols_per_row)
        for i, dest in enumerate(destinations):
            with cols[i % cols_per_row]:
                label = f"**{dest['iata']}** — {dest['city']}"
                if st.checkbox(label, key=f"dest_{hub_airport}_{dest['iata']}"):
                    selected_dests.append(dest['iata'])

        # ─── Always-visible start button ───
        scrape_state = get_scrape_state()
        is_running = scrape_state["status"] == "running"
        scrape_disabled = is_running or not (selected_dests and hub_days)
        if is_running:
            btn_label = "⏳ Scrape in progress..."
        elif selected_dests and hub_days:
            btn_label = (
                f"🚀 Scrape {len(selected_dests)} route"
                f"{'s' if len(selected_dests) != 1 else ''} × {len(hub_days)} day"
                f"{'s' if len(hub_days) != 1 else ''}"
            )
        else:
            btn_label = "🚀 Select at least one destination and one day"

        scrape_btn = st.button(
            btn_label,
            key="hub_scrape",
            use_container_width=True,
            type="primary",
            disabled=scrape_disabled,
        )

        if selected_dests and hub_days and not is_running:
            route_list = ', '.join(f'{hub_airport}-{d}' for d in selected_dests)
            day_list = ', '.join(get_day_label(d) for d in hub_days)
            st.caption(f"Selected: {route_list} | Days: {day_list}")

        if scrape_btn and not scrape_disabled:
            routes = [(hub_airport, d) for d in selected_dests]
            dates = [datetime.combine(datetime.now().date() + timedelta(days=d),
                     datetime.min.time()) for d in hub_days]
            log_handler.clear()
            start_scrape_thread(routes, dates, headless=headless, origin="hub")
            st.rerun()


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

    scrape_state = get_scrape_state()
    is_running = scrape_state["status"] == "running"
    cp_btn = st.button(
        "⏳ Scrape in progress..." if is_running else "🚀 Scrape Route",
        key="cp_scrape",
        use_container_width=True,
        type="primary",
        disabled=is_running,
    )

    if cp_btn:
        if not cp_origin or not cp_dest or len(cp_origin) != 3 or len(cp_dest) != 3:
            st.error("Please enter valid 3-letter airport codes.")
        elif not cp_days:
            st.error("Select at least one day to check.")
        else:
            routes = [(cp_origin, cp_dest)]
            dates = [datetime.combine(datetime.now().date() + timedelta(days=d), datetime.min.time())
                     for d in cp_days]
            log_handler.clear()
            start_scrape_thread(routes, dates, headless=headless, origin="cp")
            st.rerun()


# ─── Global live status panel (rendered once, below the tabs) ───
_scrape_state = get_scrape_state()
if _scrape_state["status"] != "idle":
    st.markdown("---")
    st.markdown("### Live scrape status")
    render_scrape_live()

# ─── Results panel (always visible when any results exist) ───
if 'hub_results' in st.session_state or 'cp_results' in st.session_state:
    st.markdown("---")
    # Pick whichever is fresher — if a scrape just completed, use that tab's results
    origin = _scrape_state.get("origin")
    if origin == "cp" and 'cp_results' in st.session_state:
        primary_key, primary_label = 'cp_results', "City Pair"
        other_key, other_label = 'hub_results', "Hub Routes"
    else:
        primary_key, primary_label = 'hub_results', "Hub Routes"
        other_key, other_label = 'cp_results', "City Pair"

    st.markdown(f"## 📊 Results — {primary_label}")
    if primary_key in st.session_state and st.session_state[primary_key]:
        display_results(st.session_state[primary_key])
    else:
        st.info("No results yet.")

    if other_key in st.session_state and st.session_state[other_key]:
        with st.expander(f"📊 Previous {other_label} results", expanded=False):
            display_results(st.session_state[other_key])

# Auto-refresh while a scrape is running
if _scrape_state["status"] == "running":
    time.sleep(1.0)
    st.rerun()
