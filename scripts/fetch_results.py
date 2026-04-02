#!/usr/bin/env python3
"""
Fetch NFL game results using nflreadpy.

Uses nflreadpy (nflverse Python wrapper) to load schedule data with scores,
then extracts results for a specific season/week.

Usage:
    python scripts/fetch_results.py [--season 2024] [--week 1]

When run by the Tuesday cron (after MNF), defaults to the previous week.
"""

import argparse
import json
import sys
from pathlib import Path

import nflreadpy as nfl

ROOT = Path(__file__).resolve().parent.parent


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch NFL game results")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=None)
    return parser.parse_args()


def fetch_results(season: int, week: int) -> dict:
    """Load schedule from nflreadpy and extract results for the given week."""
    print(f"Loading schedules for {season} via nflreadpy...")
    sched = nfl.load_schedules(season)

    # Filter to regular season week
    week_games = sched.filter(
        (sched["week"] == week)
        & (sched["game_type"] == "REG")
    )

    print(f"Found {len(week_games)} regular-season games for {season} Week {week}")

    games = []
    for row in week_games.iter_rows(named=True):
        away_score = row["away_score"]
        home_score = row["home_score"]

        # Skip games without scores (not yet played)
        if away_score is None or home_score is None:
            print(f"  Skipping {row['away_team']} @ {row['home_team']} (no score)")
            continue

        away_score = int(away_score)
        home_score = int(home_score)

        if away_score > home_score:
            winner = row["away_team"]
        elif home_score > away_score:
            winner = row["home_team"]
        else:
            winner = "TIE"

        games.append({
            "game_id": row["game_id"],
            "away_team": row["away_team"],
            "home_team": row["home_team"],
            "away_score": away_score,
            "home_score": home_score,
            "winner": winner,
        })

    return {"season": season, "week": week, "games": games}


def main():
    args = get_args()

    season = args.season or nfl.get_current_season()
    week = args.week or max(1, nfl.get_current_week() - 1)

    print(f"Fetching results for {season} Week {week}...")
    data = fetch_results(season, week)

    if not data["games"]:
        print("No completed games found for this week.")
        sys.exit(0)

    results_dir = ROOT / "data" / "results" / str(season)
    results_dir.mkdir(parents=True, exist_ok=True)
    results_path = results_dir / f"week-{week}.json"
    results_path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Wrote {len(data['games'])} game results to {results_path}")


if __name__ == "__main__":
    main()
