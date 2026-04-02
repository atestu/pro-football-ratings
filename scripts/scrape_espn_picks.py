#!/usr/bin/env python3
"""
Scrape expert picks from the ESPN talentpicks API.

ESPN endpoint (undocumented):
    https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/
        seasons/{YEAR}/types/2/weeks/{WEEK}/talentpicks?limit=100

The response contains items (either inline or $ref URLs to follow).
Each resolves to one expert's set of picks for that week.

Usage:
    python scripts/scrape_espn_picks.py [--season 2024] [--week 1]
"""

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import nflreadpy as nfl

from normalize import normalize_team, make_game_id, slugify

ROOT = Path(__file__).resolve().parent.parent
ESPN_BASE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"


def fetch_json(url: str, retries: int = 3) -> dict:
    """Fetch JSON from a URL with retries."""
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "nfl-predictions/1.0"})
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    return {}


# Caches for resolved refs
_team_cache: dict[str, str] = {}
_event_cache: dict[str, dict | None] = {}


def resolve_team_abbrev(team_ref: str) -> str:
    """Resolve an ESPN team $ref to a canonical abbreviation."""
    if team_ref in _team_cache:
        return _team_cache[team_ref]
    team = fetch_json(team_ref)
    abbrev = normalize_team(team.get("abbreviation", ""))
    _team_cache[team_ref] = abbrev
    return abbrev


def resolve_event(event_ref: str) -> dict | None:
    """Resolve an ESPN event $ref to game info."""
    if event_ref in _event_cache:
        return _event_cache[event_ref]

    event = fetch_json(event_ref)
    competitions = event.get("competitions", [])
    if not competitions:
        _event_cache[event_ref] = None
        return None

    competition = competitions[0]
    away = home = None

    for comp in competition.get("competitors", []):
        if comp.get("team", {}).get("$ref"):
            abbrev = resolve_team_abbrev(comp["team"]["$ref"])
        elif comp.get("team", {}).get("abbreviation"):
            abbrev = normalize_team(comp["team"]["abbreviation"])
        else:
            continue

        if comp.get("homeAway") == "away":
            away = abbrev
        elif comp.get("homeAway") == "home":
            home = abbrev

    info = {
        "kickoff": event.get("date") or competition.get("date"),
        "away": away,
        "home": home,
    }
    _event_cache[event_ref] = info
    return info


def scrape_picks(season: int, week: int) -> dict:
    """Fetch all talent picks for a given season/week from ESPN."""
    url = f"{ESPN_BASE}/seasons/{season}/types/2/weeks/{week}/talentpicks?limit=100"
    print(f"Fetching: {url}")

    index = fetch_json(url)
    items = index.get("items", [])
    print(f"Found {len(items)} talent pick entries")

    games: dict[str, dict] = {}
    picks: list[dict] = []
    experts: dict[str, dict] = {}

    for item in items:
        # Follow $ref if needed
        if "$ref" in item:
            try:
                pick_data = fetch_json(item["$ref"])
            except Exception as e:
                print(f"  Warning: failed to resolve pick ref: {e}")
                continue
        else:
            pick_data = item

        # Extract expert info
        talent = pick_data.get("talent")
        if not talent:
            continue

        if "$ref" in talent:
            try:
                talent = fetch_json(talent["$ref"])
            except Exception:
                continue

        expert_name = talent.get("displayName") or talent.get("shortName") or "Unknown"
        expert_slug = slugify(expert_name)

        experts[expert_slug] = {
            "expert": expert_slug,
            "expert_name": expert_name,
            "source": "espn_talentpicks",
            "outlet": "ESPN",
        }

        # Extract picks
        expert_picks = pick_data.get("picks") or pick_data.get("events") or []
        for pick in expert_picks:
            # Resolve event
            event_info = None
            event_ref = (pick.get("event") or {}).get("$ref")
            if event_ref:
                try:
                    event_info = resolve_event(event_ref)
                except Exception:
                    continue

            if not event_info or not event_info["away"] or not event_info["home"]:
                continue

            game_id = make_game_id(season, week, event_info["away"], event_info["home"])

            if game_id not in games:
                games[game_id] = {
                    "game_id": game_id,
                    "away_team": event_info["away"],
                    "home_team": event_info["home"],
                    "kickoff": event_info["kickoff"],
                }

            # Determine picked team
            picked_team = None
            for key_path in [
                ("competitor", "$ref"),
                ("competitor", "team", "$ref"),
                ("pick", "team", "$ref"),
            ]:
                obj = pick
                for k in key_path[:-1]:
                    obj = obj.get(k, {}) if isinstance(obj, dict) else {}
                ref = obj.get(key_path[-1]) if isinstance(obj, dict) else None
                if ref:
                    try:
                        picked_team = resolve_team_abbrev(ref)
                    except Exception:
                        pass
                    break

            if not picked_team:
                for key_path in [
                    ("competitor", "abbreviation"),
                    ("pick", "abbreviation"),
                ]:
                    obj = pick
                    for k in key_path[:-1]:
                        obj = obj.get(k, {}) if isinstance(obj, dict) else {}
                    abbrev = obj.get(key_path[-1]) if isinstance(obj, dict) else None
                    if abbrev:
                        picked_team = normalize_team(abbrev)
                        break

            if not picked_team:
                continue

            picks.append({
                "expert": expert_slug,
                "expert_name": expert_name,
                "source": "espn_talentpicks",
                "outlet": "ESPN",
                "game_id": game_id,
                "pick": picked_team,
                "pick_type": "straight_up",
            })

    return {
        "season": season,
        "week": week,
        "season_type": "REG",
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": ["espn_talentpicks"],
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
    for expert in new_experts:
        if expert["expert"] not in existing:
            registry["experts"].append(expert)
            existing.add(expert["expert"])
            print(f"  New expert: {expert['expert_name']} ({expert['outlet']})")

    registry_path.write_text(json.dumps(registry, indent=2) + "\n")


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape ESPN expert picks")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=None)
    return parser.parse_args()


def main():
    args = get_args()

    season = args.season or nfl.get_current_season()
    week = args.week or nfl.get_current_week()

    print(f"Scraping ESPN picks for {season} Week {week}...")

    data = scrape_picks(season, week)
    new_experts = data.pop("_experts")

    # Write picks file
    picks_dir = ROOT / "data" / "picks" / str(season)
    picks_dir.mkdir(parents=True, exist_ok=True)
    picks_path = picks_dir / f"week-{week}.json"
    picks_path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Wrote {len(data['picks'])} picks across {len(data['games'])} games to {picks_path}")

    # Update expert registry
    update_experts_registry(new_experts)
    print("Done.")


if __name__ == "__main__":
    main()
