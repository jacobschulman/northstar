#!/usr/bin/env python3
"""
Northstar CLI — United Airlines seat availability monitor.

Usage:
  python run.py                              # Full scrape + CLI report
  python run.py --hub EWR                    # Scrape a single hub only
  python run.py --routes EWR-LHR,SFO-NRT     # Specific routes only
  python run.py --force-refresh               # Bypass tiered staleness, re-scrape everything
  python run.py --no-headless                 # Visible browser for debugging
  python run.py --report-only                 # Regenerate report from latest data (no scraping)
  python run.py --merge-only                  # Merge per-hub data files into latest.json + report
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
        '--hub', type=str, default=None,
        help='Scrape only routes for a specific hub (e.g. EWR, SFO, ORD, IAD, IAH).'
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
        '--merge-only', action='store_true',
        help='Merge per-hub data files into latest.json and generate report (no scraping).'
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
    parser.add_argument(
        '--data-dir', type=str, default='data',
        help='Directory for data files (default: data).'
    )

    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger(__name__)

    headless = not args.no_headless

    # Build routes filter from --hub or --routes
    routes_filter = None
    if args.hub:
        hub = args.hub.upper()
        import json
        from pathlib import Path
        config_file = Path(args.config)
        if config_file.exists():
            with open(config_file) as f:
                config = json.load(f)
            hub_routes = [
                f"{r['origin']}-{r['destination']}"
                for r in config.get("routes", [])
                if r.get("hub", r["origin"]) == hub
            ]
            routes_filter = hub_routes
            logger.info(f"Hub filter: {hub} ({len(hub_routes)} routes)")
        else:
            logger.error(f"Config file not found: {args.config}")
            sys.exit(1)
    elif args.routes:
        routes_filter = args.routes.split(',')

    # Determine output data path (per-hub or default)
    data_dir = args.data_dir
    if args.hub:
        data_file = f"{data_dir}/hub_{args.hub.upper()}.json"
    else:
        data_file = f"{data_dir}/latest.json"

    if args.merge_only:
        # Merge per-hub data files into latest.json
        from scraper.main import merge_hub_data, get_all_flights_from_latest
        merge_hub_data(data_dir=data_dir)
        flights = get_all_flights_from_latest(data_path=f"{data_dir}/latest.json")

    elif args.report_only:
        # Load existing data and output report
        from scraper.main import get_all_flights_from_latest
        flights = get_all_flights_from_latest(data_path=f"{data_dir}/latest.json")

    else:
        # Run the scraper
        from scraper.main import run_scraper
        flights = asyncio.run(
            run_scraper(
                config_path=args.config,
                routes_filter=routes_filter,
                force_refresh=args.force_refresh,
                headless=headless,
                data_path=data_file,
            )
        )

        # After scraping, report uses all latest data (including previous runs)
        if not args.json and not args.hub:
            from scraper.main import get_all_flights_from_latest
            flights = get_all_flights_from_latest(data_path=f"{data_dir}/latest.json")

    # Output
    if args.json:
        from report.cli import print_json
        print_json(flights)
    elif not args.hub:
        # Skip CLI report for per-hub runs (merge step will do it)
        from report.cli import print_report
        print_report(flights)

    # Generate HTML report (skip for per-hub runs — merge step handles it)
    if not args.hub and (args.html or args.merge_only or (not args.json)):
        try:
            from report.generator import generate_html_report
            generate_html_report(flights, config_path=args.config)
            logger.info("HTML report generated in docs/")
        except ImportError:
            pass  # jinja2 not installed, skip HTML report
        except Exception as e:
            logger.warning(f"HTML report generation failed: {e}")


if __name__ == "__main__":
    main()
