"""Northstar — United Airlines seat availability scraper."""

from .models import FlightData
from .main import run_scraper, get_all_flights_from_latest
