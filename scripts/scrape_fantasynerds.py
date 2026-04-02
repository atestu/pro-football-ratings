#!/usr/bin/env python3
"""
Scrape expert picks from Fantasy Nerds.

Fantasy Nerds aggregates NFL expert picks from ESPN, CBS Sports, Yahoo,
NFL Network, and many more outlets. Data is in server-rendered HTML.

Pages used:
    /nfl/picks              - Game list with game IDs (always shows latest week)
    /nfl/picks/{week}/{id}  - Per-game expert picks with team in img alt/src

Usage:
    python scripts/scrape_fantasynerds.py [--season 2025] [--week 1]
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

import nflreadpy as nfl

from normalize import normalize_team, make_game_id, slugify

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "https://www.fantasynerds.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
}

# Map full team names (from Fantasy Nerds alt text) to abbreviations
TEAM_NAME_MAP: dict[str, str] = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN",
    "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LA", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE",
    "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "N.Y. Giants": "NYG", "N.Y. Jets": "NYJ",
    "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA",
    "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN",
    "Washington Commanders": "WAS",
}


def fetch_html(url: str) -> str:
    """Fetch HTML from a URL."""
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def team_from_img(img_tag: str) -> str | None:
    """Extract team abbreviation from an <img> tag.
    Tries alt text first (full name or abbreviation), then src filename.
    """
    # Try alt text as full team name
    alt = re.search(r'alt="([^"]+)"', img_tag)
    if alt:
        name = alt.group(1).strip()
        if name in TEAM_NAME_MAP:
            return TEAM_NAME_MAP[name]
        # Try as abbreviation directly
        upper = name.upper()
        if len(upper) <= 4:
            return normalize_team(upper)

    # Try src filename: /images/nfl/teams_small2/NO.png
    src = re.search(r'src="[^"]*?/(\w+)\.(?:png|svg|jpg)"', img_tag)
    if src:
        return normalize_team(src.group(1).upper())

    return None


def get_game_ids_for_week(week: int) -> list[str]:
    """Get Fantasy Nerds game IDs for a specific week.

    The /nfl/picks page always shows the latest week regardless of ?week=.
    But each game page at /nfl/picks/{week}/{id} works for any week.
    We fetch the page and extract game IDs from the links, using the week
    number in the URL to verify we have the right week.
    """
    # Try fetching the picks page - it shows the latest week
    url = f"{BASE_URL}/nfl/picks"
    print(f"  Fetching game list: {url}")
    html = fetch_html(url)

    # Extract all game links with their week numbers
    links = re.findall(r'/nfl/picks/(\d+)/(\d+)', html)

    # Get the week that the page is showing
    page_week = int(links[0][0]) if links else None

    if page_week == week:
        game_ids = list(dict.fromkeys(l[1] for l in links))
        return game_ids

    # If the page shows a different week, we need to figure out the game IDs
    # for our target week. Fantasy Nerds game IDs are sequential, so we can
    # estimate based on the offset.
    # Better approach: just try sequential IDs and see which ones return data
    print(f"  Page shows week {page_week}, need week {week}")

    # Get game IDs from the page for reference
    ref_ids = [int(l[1]) for l in links]
    games_per_week = len(set(l[1] for l in links))
    if not ref_ids:
        return []

    # Estimate: IDs are roughly sequential. ~16 games per week.
    week_diff = page_week - week
    estimated_start = min(ref_ids) - (week_diff * games_per_week)

    # Try a range around the estimate
    valid_ids = []
    for candidate_id in range(estimated_start - 2, estimated_start + games_per_week + 2):
        try:
            test_url = f"{BASE_URL}/nfl/picks/{week}/{candidate_id}"
            req = Request(test_url, headers=HEADERS, method="HEAD")
            with urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    valid_ids.append(str(candidate_id))
        except Exception:
            continue

        if len(valid_ids) >= games_per_week:
            break

    return valid_ids


def scrape_game_picks(week: int, fn_game_id: str) -> tuple[dict | None, list[dict]]:
    """
    Scrape expert picks for a single game.
    Returns (game_info, picks) where game_info has away/home teams.
    """
    url = f"{BASE_URL}/nfl/picks/{week}/{fn_game_id}"
    html = fetch_html(url)

    # Determine the two teams from the game page
    # The page title or header usually has "TEAM at TEAM" or team images
    # Find the two main team images (teams_mid size) in the consensus section
    team_imgs = re.findall(
        r'<img[^>]*src="[^"]*teams_mid[^"]*"[^>]*alt="([^"]*)"[^>]*/?>',
        html,
    )
    teams = []
    for alt in team_imgs:
        abbr = TEAM_NAME_MAP.get(alt)
        if abbr and abbr not in teams:
            teams.append(abbr)

    away = teams[0] if len(teams) >= 1 else None
    home = teams[1] if len(teams) >= 2 else None

    # Parse expert picks table
    picks = []
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    for row in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        if len(cells) < 4:
            continue

        outlet = re.sub(r'<[^>]+>', '', cells[0]).strip()
        name_match = re.search(r'>([^<]+)</a>', cells[1])
        name = name_match.group(1).strip() if name_match else re.sub(r'<[^>]+>', '', cells[1]).strip()

        if not name or not outlet:
            continue

        # The pick is in the last cell as a team image
        pick_img = re.search(r'<img[^>]*(?:alt="([^"]*)"[^>]*src="([^"]*)"'
                             r'|src="([^"]*)"[^>]*alt="([^"]*)")', cells[-1])
        if not pick_img:
            continue

        alt_text = pick_img.group(1) or pick_img.group(4) or ""
        src_text = pick_img.group(2) or pick_img.group(3) or ""

        # Get team from alt (full name) or src (filename)
        picked_team = TEAM_NAME_MAP.get(alt_text)
        if not picked_team:
            src_match = re.search(r'/(\w+)\.(?:png|svg)', src_text)
            if src_match:
                picked_team = normalize_team(src_match.group(1).upper())

        if not picked_team:
            continue

        picks.append({
            "expert_name": name,
            "outlet": outlet,
            "pick": picked_team,
        })

    game_info = None
    if away and home:
        game_info = {"away_team": away, "home_team": home}
    elif picks:
        # Infer teams from what experts picked
        picked_teams = list(dict.fromkeys(p["pick"] for p in picks))
        if len(picked_teams) == 2:
            game_info = {"away_team": picked_teams[0], "home_team": picked_teams[1]}

    return game_info, picks


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


def scrape_week(season: int, week: int) -> dict:
    """Scrape all expert picks for a given week."""

    # Load schedule for canonical game IDs (away/home order from nflverse)
    print("  Loading nflverse schedule for game ID lookup...")
    schedule_lookup = load_schedule(season, week)

    # For the current/latest week, get game IDs from the picks page
    # For historical weeks, we need to find the IDs
    url = f"{BASE_URL}/nfl/picks"
    html = fetch_html(url)
    links = re.findall(r'/nfl/picks/(\d+)/(\d+)', html)
    page_week = int(links[0][0]) if links else None

    if page_week == week:
        fn_game_ids = list(dict.fromkeys(l[1] for l in links if int(l[0]) == week))
    else:
        # For non-current weeks, estimate game IDs
        ref_ids = sorted(set(int(l[1]) for l in links))
        games_per_week = len(ref_ids)
        week_diff = page_week - week
        est_start = ref_ids[0] - (week_diff * games_per_week)

        fn_game_ids = []
        for cid in range(est_start - 2, est_start + games_per_week + 4):
            try:
                test_html = fetch_html(f"{BASE_URL}/nfl/picks/{week}/{cid}")
                if '<table' in test_html and 'picks' in test_html.lower():
                    fn_game_ids.append(str(cid))
            except Exception:
                continue
            time.sleep(0.3)
            if len(fn_game_ids) >= 16:
                break

    print(f"  Found {len(fn_game_ids)} games for week {week}")

    all_games = []
    all_picks = []
    experts: dict[str, dict] = {}

    for fn_id in fn_game_ids:
        game_info, game_picks = scrape_game_picks(week, fn_id)
        time.sleep(0.5)

        if not game_info or not game_picks:
            continue

        team1 = game_info["away_team"]
        team2 = game_info["home_team"]

        # Look up canonical game ID from nflverse schedule
        pair = frozenset([team1, team2])
        game_id = schedule_lookup.get(pair)
        if not game_id:
            # Fallback: use the order from Fantasy Nerds
            game_id = make_game_id(season, week, team1, team2)
            print(f"  Warning: no schedule match for {team1}/{team2}, using {game_id}")

        # Parse away/home from game_id
        parts = game_id.split("_")
        away, home = parts[2], parts[3]

        all_games.append({
            "game_id": game_id,
            "away_team": away,
            "home_team": home,
        })

        for p in game_picks:
            slug = slugify(p["expert_name"])
            experts[slug] = {
                "expert": slug,
                "expert_name": p["expert_name"],
                "source": "fantasynerds",
                "outlet": p["outlet"],
            }
            all_picks.append({
                "expert": slug,
                "expert_name": p["expert_name"],
                "source": "fantasynerds",
                "outlet": p["outlet"],
                "game_id": game_id,
                "pick": p["pick"],
                "pick_type": "straight_up",
            })

    return {
        "season": season,
        "week": week,
        "season_type": "REG",
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": ["fantasynerds"],
        "games": all_games,
        "picks": all_picks,
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
    parser = argparse.ArgumentParser(description="Scrape Fantasy Nerds expert picks")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=None)
    return parser.parse_args()


def main():
    args = get_args()

    season = args.season or nfl.get_current_season()
    week = args.week or nfl.get_current_week()

    print(f"Scraping Fantasy Nerds picks for {season} Week {week}...")

    data = scrape_week(season, week)
    new_experts = data.pop("_experts")

    picks_dir = ROOT / "data" / "picks" / str(season)
    picks_dir.mkdir(parents=True, exist_ok=True)

    picks_path = picks_dir / f"week-{week}-fantasynerds.json"
    picks_path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Wrote {len(data['picks'])} picks across {len(data['games'])} games to {picks_path}")

    update_experts_registry(new_experts)
    print("Done.")


if __name__ == "__main__":
    main()
