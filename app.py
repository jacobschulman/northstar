import streamlit as st
import asyncio
import sys
from pathlib import Path
import json

# Add scraper directory to path
sys.path.append(str(Path(__file__).parent / "scraper"))

from main import UnitedScraper

st.set_page_config(
    page_title="United Cabin Crawler",
    page_icon="✈️",
    layout="centered"
)

# Custom CSS for United Airlines styling + sticky header
st.markdown("""
<style>
    /* United blue color scheme */
    :root {
        --united-blue: #0E3B7C;
        --united-light-blue: #1E5BA8;
        --united-dark: #001E4E;
    }
    
    /* Sticky header */
    .main > div:first-child {
        position: sticky;
        top: 0;
        background: white;
        z-index: 999;
        padding-top: 1rem;
        padding-bottom: 0.5rem;
        border-bottom: 3px solid var(--united-blue);
        margin-bottom: 1rem;
    }
    
    /* Title styling */
    h1 {
        color: var(--united-blue) !important;
        font-weight: 700 !important;
        margin-bottom: 0.25rem !important;
    }
    
    
    /* Subtitle */
    .subtitle {
        color: #666;
        font-size: 0.95rem;
        margin-bottom: 1rem;
    }

    
    /* Form styling */
    .stForm {
        background: #f8f9fa;
        padding: 1.5rem;
        border-radius: 8px;
        border: 1px solid #e0e0e0;
    }

    /* Help text visibility */
    .stTextInput label small, .stNumberInput label small, .stCheckbox label small {
        color: #ccc;
    }
    
    /* Button styling - United blue */
    .stButton>button {
        background-color: var(--united-blue) !important;
        color: white !important;
        font-weight: 600 !important;
        border: none !important;
        padding: 0.75rem 2rem !important;
        border-radius: 4px !important;
        transition: background-color 0.2s !important;
    }
    
    .stButton>button:hover {
        background-color: var(--united-light-blue) !important;
    }
    
    /* Radio buttons - United style */
    .stRadio > label {
        font-weight: 600;
        color: var(--united-dark);
    }

    
    /* Subheaders */
    h3 {
        color: var(--united-dark) !important;
        font-weight: 600 !important;
        margin-top: 1rem !important;
    }
    
    /* Dataframe full width */
    .stDataFrame {
        width: 100% !important;
    }
    
    /* Info boxes */
    .stAlert {
        border-radius: 4px;
    }
</style>
""", unsafe_allow_html=True)

st.title("✈️ United Cabin Crawler 💺")
st.markdown('<p class="subtitle">Monitor seat availability, upgrade lists, and standby counts for non-rev travel</p>', unsafe_allow_html=True)

# Input form
with st.form("scraper_form"):
    st.subheader("Flight Configuration")
    
    col1, col2 = st.columns(2)
    
    with col1:
        origin = st.text_input(
            "Origin Airport", 
            value="EWR",
            max_chars=3,
            help="3-letter airport code (e.g., EWR, SFO)"
        ).upper()
    
    with col2:
        destination = st.text_input(
            "Destination Airport",
            value="LHR", 
            max_chars=3,
            help="3-letter airport code (e.g., LHR, NRT)"
        ).upper()
    
    flight_numbers = st.text_input(
        "Flight Numbers (optional)",
        value="",
        placeholder="Leave blank to auto-discover",
        help="Enter comma-separated flight numbers (e.g., 14, 16, 110). Do not include 'UA' prefix."
    )
    
    st.markdown("**Days to Check**")
    col_day1, col_day2, col_day3 = st.columns(3)
    
    with col_day1:
        check_today = st.checkbox("Today", value=True)
    with col_day2:
        check_tomorrow = st.checkbox("Tomorrow", value=False)
    with col_day3:
        check_plus2 = st.checkbox("+2 Days", value=False)
    
    col_filter1, col_filter2 = st.columns(2)
    
    with col_filter1:
        direct_only = st.checkbox(
            "Direct Flights Only",
            value=True,
            help="When auto-discovering, only include non-stop flights"
        )
    
    with col_filter2:
        # Only show max flights control if connections are enabled
        if not direct_only:
            max_flights = st.number_input(
                "Max Flights to Scrape",
                min_value=1,
                max_value=50,
                value=10,
                help="Limit total flights scraped (connections count as multiple segments)"
            )
        else:
            max_flights = 999  # No limit for direct flights
    
    submitted = st.form_submit_button("🚀 Search Flights", use_container_width=True)

if submitted:
    if not origin or not destination:
        st.error("Please enter both origin and destination airports")
    elif not (check_today or check_tomorrow or check_plus2):
        st.error("Please select at least one day to check")
    else:
        # Calculate days_ahead based on checkboxes
        days_to_check = []
        if check_today:
            days_to_check.append(0)
        if check_tomorrow:
            days_to_check.append(1)
        if check_plus2:
            days_to_check.append(2)
        
        days_ahead = max(days_to_check) + 1  # For the config
        
        # Parse flight numbers
        flight_nums = []
        if flight_numbers.strip():
            try:
                flight_nums = [int(x.strip()) for x in flight_numbers.split(",")]
                st.info(f"🎯 Using specified flights: {flight_nums}")
            except ValueError:
                st.error("Invalid flight numbers. Please enter comma-separated numbers.")
                st.stop()
        else:
            st.info("🔍 Auto-discovering flights...")
        
        # Create config
        config = {
            "routes": [
                {
                    "origin": origin,
                    "destination": destination,
                    "flight_numbers": flight_nums
                }
            ],
            "days_ahead": int(days_ahead),
            "delay_min": 2,
            "delay_max": 5,
            "include_connections": not direct_only,
            "max_flights": int(max_flights)
        }
        
        # Save config
        config_dir = Path("config")
        config_dir.mkdir(exist_ok=True)
        with open(config_dir / "routes.json", "w") as f:
            json.dump(config, f, indent=2)
        
        # Run scraper
        st.info("✈️ Starting search... This will take 1-2 minutes.")
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            # Run the scraper
            scraper = UnitedScraper()
            
            # Create a wrapper to show progress
            async def run_with_progress():
                status_text.text("Initializing browser...")
                progress_bar.progress(0.1)
                
                await scraper.run()
                
                progress_bar.progress(1.0)
                status_text.text("Complete!")
            
            # Run async function
            asyncio.run(run_with_progress())
            
            st.success("✅ Scraping complete!")
            
            # Find the latest data directory
            data_dir = Path("data")
            if data_dir.exists():
                latest_run = sorted(data_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[0]
                
                # Load summary
                summary_file = latest_run / "summary.json"
                if summary_file.exists():
                    with open(summary_file) as f:
                        summary = json.load(f)
                    
                    st.subheader("Results")
                    st.write(f"**Total flights found:** {summary['total_flights']}")
                    
                    st.markdown("**Legend:** 🔴 More standbys than seats | 🟡 Close | 🟢 Good availability")
                    
                    # Show route details
                    for route_key, route_data in summary['routes'].items():
                        st.markdown(f"### {route_key}")
                        flights = route_data['flights']
                        
                        if not flights:
                            st.warning("No flights found")
                            continue
                        
                        # Sort flights by date and departure time
                        flights_sorted = sorted(flights, key=lambda f: (f['flight_date'], f['departure_time']))
                        
                        # Create table data
                        table_data = []
                        current_date = None
                        
                        for flight in flights_sorted:
                            # Determine status indicator
                            if flight['polaris_delta'] < 0:
                                status = "🔴"
                            elif flight['polaris_available'] <= 2:
                                status = "🟡"
                            else:
                                status = "🟢"
                            
                            # Format date nicely (only show if different from previous)
                            flight_date = flight['flight_date']  # "2025-10-14"
                            date_obj = __import__('datetime').datetime.strptime(flight_date, "%Y-%m-%d")
                            date_display = date_obj.strftime("%a %m/%d")  # "Mon 10/14"
                            
                            if flight_date != current_date:
                                date_str = date_display
                                current_date = flight_date
                            else:
                                date_str = ""  # Don't repeat the date
                            
                            # Check if connection
                            is_connection = flight.get('is_connection', False)
                            flight_num_display = flight['flight_number'].replace('UA', '') if not is_connection else flight['flight_number']
                            
                            # Format Polaris column with comma
                            polaris_sb = flight.get('polaris_standby', flight.get('upgrade_list_waiting', 0))
                            polaris_str = f"{flight['polaris_available']} / {flight['polaris_capacity']}, {polaris_sb} waiting"
                            
                            # J Delta (Polaris business class delta)
                            j_delta = f"{status} J{flight['polaris_delta']:+d}"
                            
                            # Format Premium Plus
                            premium_str = f"{flight['premium_plus_available']} / {flight['premium_plus_capacity']}"
                            
                            # Format Economy with standby count
                            if flight['economy_available'] > 0:
                                econ_str = f"{flight['economy_available']} / {flight['economy_capacity']}, {flight['economy_standby']} standby"
                            else:
                                econ_str = f"Full, {flight['economy_standby']} standby"
                            
                            # Format times (remove seconds if present)
                            dept_time = flight['departure_time'][:5] if len(flight['departure_time']) > 5 else flight['departure_time']
                            arr_time = flight['arrival_time'][:5] if len(flight['arrival_time']) > 5 else flight['arrival_time']
                            
                            # Check if arrival is next day
                            arr_display = arr_time
                            if '+1' in flight.get('arrival_time', '') or date_obj.strftime("%d") != arr_time:
                                arr_display = f"{arr_time}+1"
                            
                            # Aircraft - show connection route if applicable
                            aircraft_display = flight.get('connection_route', flight['aircraft_type'].replace('Boeing ', '').replace('Airbus ', 'A'))
                            
                            table_data.append({
                                "Date": date_str,
                                "Flight": flight_num_display,
                                "Depart": dept_time,
                                "Arrive": arr_display,
                                "Polaris": polaris_str,
                                "Δ": j_delta,
                                "Premium": premium_str,
                                "Econ": econ_str,
                                "Aircraft": aircraft_display
                            })
                        
                        # Display as dataframe
                        import pandas as pd
                        df = pd.DataFrame(table_data)
                        
                        st.dataframe(
                            df,
                            use_container_width=True,
                            hide_index=True,
                            height=min(len(flights) * 70 + 38, 600)
                        )
                    
                    st.info(f"📁 Full data saved to: `{latest_run}`")
        
        except Exception as e:
            st.error(f"Error: {str(e)}")
            st.exception(e)

# Instructions
with st.expander("ℹ️ How to Use"):
    st.markdown("""
    ### Quick Start
    1. Enter your origin and destination airports
    2. **Leave flight numbers blank** to auto-discover all flights, or enter specific flight numbers
    3. Check "Direct Flights Only" to exclude connections (recommended)
    4. Choose how many days ahead to check
    5. Click "Search Flights"
    
    **Note:** The scraper will open a browser window in the background. The process takes 1-2 minutes depending on how many flights you're checking.
    
    ### Auto-Discovery
    When you leave flight numbers blank, the scraper will:
    - Automatically find all United flights for your route
    - Filter to non-stop flights (if "Direct Flights Only" is checked)
    - Update daily as flight schedules change
    
    ### Understanding the Results
    - 🟢 Green: Seats available, positive delta
    - 🟡 Yellow: Flight full but manageable standby list
    - 🔴 Red: Negative delta (more standbys than available seats)
    """)