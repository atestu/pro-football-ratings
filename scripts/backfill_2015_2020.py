#!/usr/bin/env python3
"""
Backfill ESPN picks and game results for 2015-2020 seasons.

Fantasy Nerds data is not available before 2021 (game IDs start at 259).
ESPN pages exist but are degraded (1-5 experts vs 10+ for recent seasons).

Usage:
    python scripts/backfill_2015_2020.py [--season 2015] [--espn-only] [--results-only]
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrape_espn_picks import scrape_picks, update_experts_registry
from fetch_results import fetch_results

ROOT = Path(__file__).resolve().parent.parent

WEEKS_PER_SEASON = {
    2015: 17, 2016: 17, 2017: 17, 2018: 17, 2019: 17, 2020: 17,
}


def backfill_espn(season: int):
    """Scrape ESPN picks for all weeks of a season."""
    max_week = WEEKS_PER_SEASON[season]
    picks_dir = ROOT / "data" / "picks" / str(season)
    picks_dir.mkdir(parents=True, exist_ok=True)

    for week in range(1, max_week + 1):
        picks_path = picks_dir / f"week-{week}.json"
        if picks_path.exists():
            print(f"  Skipping ESPN {season} Week {week} (already exists)")
            continue

        try:
            data = scrape_picks(season, week)
            new_experts = data.pop("_experts")

            picks_path.write_text(json.dumps(data, indent=2) + "\n")
            print(f"  ESPN {season} Week {week}: {len(data['picks'])} picks, {len(data['games'])} games")
            update_experts_registry(new_experts)
        except Exception as e:
            print(f"  ESPN {season} Week {week}: FAILED - {e}")

        time.sleep(1.5)


def backfill_results(season: int):
    """Fetch results for all weeks of a season."""
    max_week = WEEKS_PER_SEASON[season]
    results_dir = ROOT / "data" / "results" / str(season)
    results_dir.mkdir(parents=True, exist_ok=True)

    for week in range(1, max_week + 1):
        results_path = results_dir / f"week-{week}.json"
        if results_path.exists():
            print(f"  Skipping results {season} Week {week} (already exists)")
            continue

        try:
            data = fetch_results(season, week)
            results_path.write_text(json.dumps(data, indent=2) + "\n")
            print(f"  Results {season} Week {week}: {len(data['games'])} games")
        except Exception as e:
            print(f"  Results {season} Week {week}: FAILED - {e}")


def main():
    parser = argparse.ArgumentParser(description="Backfill 2015-2020 data")
    parser.add_argument("--season", type=int, default=None,
                        help="Single season to backfill (default: all 2015-2020)")
    parser.add_argument("--espn-only", action="store_true",
                        help="Only scrape ESPN picks")
    parser.add_argument("--results-only", action="store_true",
                        help="Only fetch results")
    args = parser.parse_args()

    seasons = [args.season] if args.season else list(range(2015, 2021))

    for season in seasons:
        if season not in WEEKS_PER_SEASON:
            print(f"Unsupported season: {season}")
            continue

        print(f"\n{'='*50}")
        print(f"Season {season} ({WEEKS_PER_SEASON[season]} weeks)")
        print(f"{'='*50}")

        if not args.results_only:
            print(f"\nScraping ESPN picks...")
            backfill_espn(season)

        if not args.espn_only:
            print(f"\nFetching results...")
            backfill_results(season)

    print("\nBackfill complete.")


if __name__ == "__main__":
    main()
