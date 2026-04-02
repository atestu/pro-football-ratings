#!/usr/bin/env python3
"""
Scrape expert picks from ProFootballTalk (NBC Sports).

PFT publishes weekly pick articles with Florio vs Simms picks at:
    https://www.nbcsports.com/nfl/profootballtalk/rumor-mill/news/pfts-week-{N}-{YEAR}-nfl-picks-florio-vs-simms

Pick lines follow the format:
    Florio's pick: Eagles 30, Cowboys 17.
    Simms's pick: Eagles 27, Cowboys 20.

The first team in each line is always the predicted winner (the expert's pick).

Usage:
    python scripts/scrape_pft_picks.py [--season 2025] [--week 1]
"""

import argparse
import json
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen

import nflreadpy as nfl

from normalize import normalize_team_name, make_game_id, slugify

ROOT = Path(__file__).resolve().parent.parent

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
}

# Map short names found in pick lines to full expert display names
EXPERT_MAP = {
    "Florio": "Mike Florio",
    "Simms": "Chris Simms",
}


def fetch_html(url: str) -> str:
    """Fetch HTML from a URL."""
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def load_schedule(season: int, week: int) -> dict[frozenset, str]:
    """Load nflverse schedule to map team pairs to canonical game IDs."""
    sched = nfl.load_schedules(season)
    week_games = sched.filter(
        (sched["week"] == week) & (sched["game_type"] == "REG")
    )
    # Map frozenset of {away, home} -> game_id
    lookup = {}
    for row in week_games.iter_rows(named=True):
        pair = frozenset([row["away_team"], row["home_team"]])
        lookup[pair] = row["game_id"]
    return lookup


def scrape_picks(season: int, week: int) -> dict:
    """Scrape all expert picks for a given season/week from PFT."""

    # Load schedule for canonical game IDs (away/home order from nflverse)
    print("  Loading nflverse schedule for game ID lookup...")
    schedule_lookup = load_schedule(season, week)

    url = (
        f"https://www.nbcsports.com/nfl/profootballtalk/rumor-mill/news/"
        f"pfts-week-{week}-{season}-nfl-picks-florio-vs-simms"
    )
    print(f"Fetching: {url}")
    html = fetch_html(url)

    # Parse pick lines: "Florio's pick: Eagles 30, Cowboys 17."
    # or "Simms's pick: Eagles 27, Cowboys 20."
    pattern = re.compile(
        r"(\w+)['`\u2019]s\s+pick:\s+"
        r"([A-Za-z0-9]+)\s+(\d+),\s+"
        r"([A-Za-z0-9]+)\s+(\d+)",
    )

    matches = pattern.findall(html)
    print(f"  Found {len(matches)} pick lines")

    games: dict[str, dict] = {}
    picks: list[dict] = []
    experts: dict[str, dict] = {}

    for expert_short, team1_name, _score1, team2_name, _score2 in matches:
        # Resolve expert name
        expert_name = EXPERT_MAP.get(expert_short)
        if not expert_name:
            print(f"  Warning: unknown expert '{expert_short}', skipping")
            continue

        # Resolve team nicknames to abbreviations
        try:
            team1 = normalize_team_name(team1_name)
        except KeyError:
            print(f"  Warning: unrecognized team '{team1_name}', skipping")
            continue
        try:
            team2 = normalize_team_name(team2_name)
        except KeyError:
            print(f"  Warning: unrecognized team '{team2_name}', skipping")
            continue

        # The first team is always the expert's pick
        picked_team = team1

        # Look up canonical game ID from nflverse schedule
        pair = frozenset([team1, team2])
        game_id = schedule_lookup.get(pair)
        if not game_id:
            # Fallback: use the order we found
            game_id = make_game_id(season, week, team1, team2)
            print(f"  Warning: no schedule match for {team1}/{team2}, using {game_id}")

        # Parse away/home from game_id
        parts = game_id.split("_")
        away, home = parts[2], parts[3]

        if game_id not in games:
            games[game_id] = {
                "game_id": game_id,
                "away_team": away,
                "home_team": home,
            }

        slug = slugify(expert_name)
        experts[slug] = {
            "expert": slug,
            "expert_name": expert_name,
            "source": "pft",
            "outlet": "ProFootballTalk",
        }

        picks.append({
            "expert": slug,
            "expert_name": expert_name,
            "source": "pft",
            "outlet": "ProFootballTalk",
            "game_id": game_id,
            "pick": picked_team,
            "pick_type": "straight_up",
        })

    return {
        "season": season,
        "week": week,
        "season_type": "REG",
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": ["pft"],
        "games": list(games.values()),
        "picks": picks,
        "_experts": list(experts.values()),
    }


def update_experts_registry(new_experts: list[dict]):
    """Update data/experts.json with any new experts."""
    registry_path = ROOT / "data" / "experts.json"
    if registry_path.exists():
        registry = json.loads(registry_path.read_text())
    else:
        registry = {"experts": []}

    existing = {e["expert"] for e in registry["experts"]}
    added = 0
    for expert in new_experts:
        if expert["expert"] not in existing:
            registry["experts"].append(expert)
            existing.add(expert["expert"])
            added += 1

    if added:
        registry_path.write_text(json.dumps(registry, indent=2) + "\n")
        print(f"  Added {added} new experts to registry")


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape PFT expert picks")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=None)
    return parser.parse_args()


def main():
    args = get_args()

    season = args.season or nfl.get_current_season()
    week = args.week or nfl.get_current_week()

    print(f"Scraping PFT picks for {season} Week {week}...")

    data = scrape_picks(season, week)
    new_experts = data.pop("_experts")

    picks_dir = ROOT / "data" / "picks" / str(season)
    picks_dir.mkdir(parents=True, exist_ok=True)

    picks_path = picks_dir / f"week-{week}-pft.json"
    picks_path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Wrote {len(data['picks'])} picks across {len(data['games'])} games to {picks_path}")

    update_experts_registry(new_experts)
    print("Done.")


if __name__ == "__main__":
    main()
