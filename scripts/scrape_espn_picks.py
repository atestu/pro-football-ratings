#!/usr/bin/env python3
"""
Scrape expert picks from ESPN.

Primary source is the picks page at:
    https://www.espn.com/nfl/picks/_/week/{WEEK}/seasontype/2/season/{YEAR}
which embeds a `picksData` object in `window['__espnfitt__']`. The page is
now behind an AWS WAF JavaScript challenge (HTTP 202 + goku challenge page),
so when it fails we fall back to the core API talentpicks endpoint:
    https://sports.core.api.espn.com/v2/.../seasons/{Y}/types/2/weeks/{W}/talentpicks

The API's `correct` flag is unreliable (always true), but the pick itself is
preserved -- verified byte-for-byte against page-scraped 2025 data. We grade
picks ourselves in score_experts.py, so only the pick matters.

Usage:
    python scripts/scrape_espn_picks.py [--season 2024] [--week 1]
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import nflreadpy as nfl

from normalize import normalize_team, make_game_id, slugify

ROOT = Path(__file__).resolve().parent.parent

CORE_API = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"

# ESPN numeric team ids as used in core-API competitor refs. Abbreviations are
# ESPN's own (WSH, LAR) and go through normalize_team().
ESPN_TEAM_IDS = {
    "1": "ATL", "2": "BUF", "3": "CHI", "4": "CIN", "5": "CLE", "6": "DAL",
    "7": "DEN", "8": "DET", "9": "GB", "10": "TEN", "11": "IND", "12": "KC",
    "13": "LV", "14": "LAR", "15": "MIA", "16": "MIN", "17": "NE", "18": "NO",
    "19": "NYG", "20": "NYJ", "21": "PHI", "22": "ARI", "23": "PIT",
    "24": "LAC", "25": "SF", "26": "SEA", "27": "TB", "28": "WSH",
    "29": "CAR", "30": "JAX", "33": "BAL", "34": "HOU",
}


def fetch_espn_picks_page(season: int, week: int) -> dict:
    """Fetch and parse the embedded picksData from ESPN's picks page."""
    url = f"https://www.espn.com/nfl/picks/_/week/{week}/seasontype/2/season/{season}"
    print(f"Fetching: {url}")

    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
    })
    with urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8")

    match = re.search(
        r"window\['__espnfitt__'\]\s*=\s*(\{.+?\});\s*</script>",
        html,
        re.DOTALL,
    )
    if not match:
        raise RuntimeError("Could not find __espnfitt__ data in ESPN page")

    data = json.loads(match.group(1))
    picks_data = data["page"]["content"]["picksData"]
    return picks_data


def team_from_logo(logo_url: str) -> str:
    """Extract team abbreviation from an ESPN team logo URL.
    e.g. 'https://a.espncdn.com/i/teamlogos/nfl/500/kc.png' -> 'KC'
    """
    filename = logo_url.rsplit("/", 1)[-1]  # 'kc.png'
    abbrev = filename.replace(".png", "").replace(".svg", "").upper()
    return normalize_team(abbrev)


def fetch_talent_picks(season: int, week: int) -> list[dict]:
    """Fetch all talentpicks items from the core API, following pagination."""
    items: list[dict] = []
    page = 1
    while True:
        url = (
            f"{CORE_API}/seasons/{season}/types/2/weeks/{week}/talentpicks"
            f"?limit=300&page={page}"
        )
        print(f"Fetching: {url}")
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        items.extend(data.get("items", []))
        if page >= data.get("pageCount", 1):
            break
        page += 1
    return items


def scrape_picks_from_api(season: int, week: int) -> dict:
    """Build the picks payload from the core-API talentpicks endpoint.

    Competitor refs look like .../events/{event}/competitions/{event}/
    competitors/{teamId}; the event id maps to a canonical game via the
    nflverse schedule's `espn` column.
    """
    items = fetch_talent_picks(season, week)

    sched = nfl.load_schedules(season)
    week_games = sched.filter(
        (sched["week"] == week) & (sched["game_type"] == "REG")
    )
    ev_lookup = {
        str(r["espn"]): (r["game_id"], r["away_team"], r["home_team"])
        for r in week_games.iter_rows(named=True)
    }

    ref_re = re.compile(r"events/(\d+)/competitions/\d+/competitors/(\d+)")
    games: dict[str, dict] = {}
    picks: list[dict] = []
    experts: dict[str, dict] = {}

    for item in items:
        pick = item.get("pick") or {}
        person = pick.get("person") or {}
        full_name = person.get("displayName")
        m = ref_re.search((pick.get("competitor") or {}).get("$ref", ""))
        if not (full_name and m):
            continue
        event_id, team_id = m.group(1), m.group(2)

        entry = ev_lookup.get(event_id)
        if entry is None:
            print(f"  Warning: event {event_id} not in nflverse schedule, skipping")
            continue
        game_id, away, home = entry

        abbr = ESPN_TEAM_IDS.get(team_id)
        if abbr is None:
            print(f"  Warning: unknown ESPN team id {team_id} in {game_id}")
            continue
        picked_team = normalize_team(abbr)

        slug = slugify(full_name)
        games[game_id] = {
            "game_id": game_id,
            "away_team": away,
            "home_team": home,
            "kickoff": None,
        }
        experts[slug] = {
            "expert": slug,
            "expert_name": full_name,
            "source": "espn_talentpicks",
            "outlet": "ESPN",
        }
        picks.append({
            "expert": slug,
            "expert_name": full_name,
            "source": "espn_talentpicks",
            "outlet": "ESPN",
            "game_id": game_id,
            "pick": picked_team,
            "pick_type": "straight_up",
        })

    print(f"Found {len(experts)} experts")
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


def scrape_picks(season: int, week: int) -> dict:
    """Scrape all expert picks, preferring the page, falling back to the API."""
    try:
        return scrape_picks_from_page(season, week)
    except Exception as e:
        print(f"  Page scrape failed ({e}); falling back to core API")
        return scrape_picks_from_api(season, week)


def scrape_picks_from_page(season: int, week: int) -> dict:
    """Scrape all expert picks for a given season/week from the picks page."""
    picks_data = fetch_espn_picks_page(season, week)

    # Parse header for expert info (index 0 is empty/game column)
    header = picks_data["header"]
    expert_list = []
    for h in header:
        if isinstance(h, dict) and "name" in h:
            full_name = h.get("headshot", {}).get("alt", h["name"])
            expert_list.append({
                "index": header.index(h),
                "slug": slugify(full_name),
                "name": full_name,
                "espn_id": h.get("id"),
                "week_record": h.get("weekRecord"),
            })

    print(f"Found {len(expert_list)} experts")

    games: dict[str, dict] = {}
    picks: list[dict] = []
    experts: dict[str, dict] = {}

    for row in picks_data["rows"]:
        # First element is the game info
        game_info = row[0]
        teams_str = game_info.get("teams", "")  # e.g. "BAL at KC"
        kickoff = game_info.get("date")

        # Parse teams from "AWAY at HOME" or "AWAY VS HOME"
        parts = re.split(r"\s+(?:at|AT|vs|VS|@)\s+", teams_str)
        if len(parts) != 2:
            print(f"  Warning: could not parse teams from '{teams_str}'")
            continue

        away = normalize_team(parts[0].strip())
        home = normalize_team(parts[1].strip())
        game_id = make_game_id(season, week, away, home)

        games[game_id] = {
            "game_id": game_id,
            "away_team": away,
            "home_team": home,
            "kickoff": kickoff,
        }

        # Each subsequent element is an expert's pick for this game
        for expert in expert_list:
            cell = row[expert["index"]]
            if not isinstance(cell, dict):
                continue

            # Get picked team from logo URL
            logo = cell.get("logo")
            if not logo:
                continue

            picked_team = team_from_logo(logo)

            experts[expert["slug"]] = {
                "expert": expert["slug"],
                "expert_name": expert["name"],
                "source": "espn_talentpicks",
                "outlet": "ESPN",
            }

            picks.append({
                "expert": expert["slug"],
                "expert_name": expert["name"],
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

    # get_current_week() returns 19-22 during the playoffs, but picks pages
    # only exist for the regular season
    if args.week is None and week > 18:
        print(f"Auto-detected week {week} is postseason; nothing to scrape.")
        return

    print(f"Scraping ESPN picks for {season} Week {week}...")

    data = scrape_picks(season, week)
    if not data["picks"]:
        raise RuntimeError(
            f"No picks found for {season} week {week} -- refusing to write an "
            "empty picks file"
        )
    new_experts = data.pop("_experts")

    # Write picks file
    picks_dir = ROOT / "data" / "picks" / str(season)
    picks_dir.mkdir(parents=True, exist_ok=True)
    picks_path = picks_dir / f"week-{week}.json"
    picks_path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Wrote {len(data['picks'])} picks across {len(data['games'])} games to {picks_path}")

    update_experts_registry(new_experts)
    print("Done.")


if __name__ == "__main__":
    main()
