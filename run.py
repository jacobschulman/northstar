#!/usr/bin/env python3
"""
Northstar CLI — United Airlines seat availability monitor.

Usage:
  python run.py                              # Full scrape + CLI report
  python run.py --routes EWR-LHR,SFO-NRT     # Specific routes only
  python run.py --force-refresh               # Bypass tiered staleness, re-scrape everything
  python run.py --no-headless                 # Visible browser for debugging
  python run.py --report-only                 # Regenerate report from latest data (no scraping)
  python run.py --json                        # Output raw JSON to stdout
"""

import argparse
import asyncio
import logging
import sys


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('scraper.log'),
            logging.StreamHandler(sys.stderr),  # Log to stderr so --json stdout is clean
        ]
    )


def main():
    parser = argparse.ArgumentParser(
        description="Northstar — United Airlines seat availability monitor"
    )
    parser.add_argument(
        '--routes', type=str, default=None,
        help='Comma-separated routes to scrape (e.g. EWR-LHR,SFO-NRT). Default: all configured routes.'
    )
    parser.add_argument(
        '--force-refresh', action='store_true',
        help='Bypass tiered staleness checks, re-scrape everything.'
    )
    parser.add_argument(
        '--no-headless', action='store_true',
        help='Run browser with visible window (for debugging).'
    )
    parser.add_argument(
        '--headless', action='store_true', default=True,
        help='Run browser in headless mode (default).'
    )
    parser.add_argument(
        '--report-only', action='store_true',
        help='Skip scraping, generate report from latest data.'
    )
    parser.add_argument(
        '--json', action='store_true',
        help='Output results as JSON to stdout.'
    )
    parser.add_argument(
        '--html', action='store_true',
        help='Generate static HTML report to docs/ directory.'
    )
    parser.add_argument(
        '--config', type=str, default='config/routes.json',
        help='Path to routes config file.'
    )

    args = parser.parse_args()

    setup_logging()

    headless = not args.no_headless
    routes_filter = args.routes.split(',') if args.routes else None

    if args.report_only:
        # Load existing data and output report
        from scraper.main import get_all_flights_from_latest
        flights = get_all_flights_from_latest()
    else:
        # Run the scraper
        from scraper.main import run_scraper
        flights = asyncio.run(
            run_scraper(
                config_path=args.config,
                routes_filter=routes_filter,
                force_refresh=args.force_refresh,
                headless=headless,
            )
        )

        # After scraping, report uses all latest data (including previous runs)
        if not args.json:
            from scraper.main import get_all_flights_from_latest
            flights = get_all_flights_from_latest()

    # Output
    if args.json:
        from report.cli import print_json
        print_json(flights)
    else:
        from report.cli import print_report
        print_report(flights)

    # Generate HTML report if requested
    if args.html or not args.json:
        try:
            from report.generator import generate_html_report
            generate_html_report(flights)
            logging.getLogger(__name__).info("HTML report generated in docs/")
        except ImportError:
            pass  # jinja2 not installed, skip HTML report
        except Exception as e:
            logging.getLogger(__name__).warning(f"HTML report generation failed: {e}")


if __name__ == "__main__":
    main()
