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
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import nflreadpy as nfl

from normalize import normalize_team, make_game_id, slugify

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "https://www.fantasynerds.com"
WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
WAYBACK_BASE = "https://web.archive.org/web"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
}

# Game IDs are sequential: 272 per season starting at 259 for 2021
FIRST_GAME_ID_2021 = 259
GAMES_PER_SEASON = 272


def fetch_html(url: str) -> str:
    """Fetch HTML from a URL."""
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def game_id_range_for_season(season: int) -> tuple[int, int]:
    """Return (first_id, last_id) for a given season's FN game IDs."""
    first = FIRST_GAME_ID_2021 + (season - 2021) * GAMES_PER_SEASON
    last = first + GAMES_PER_SEASON - 1
    return first, last


def _fetch_with_retries(url: str, max_retries: int = 4) -> str:
    """Fetch a URL with exponential backoff on failure."""
    for attempt in range(max_retries):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** (attempt + 1) + 1  # 3, 5, 9, 17 seconds
            print(f"    Retry {attempt + 1}/{max_retries - 1} after {wait}s ({e})")
            time.sleep(wait)


def discover_wayback_game_ids(week: int, season: int) -> list[tuple[str, str]]:
    """Use Wayback CDX API to find archived game pages for a given week.

    Returns list of (timestamp, game_id) tuples.
    """
    first_id, last_id = game_id_range_for_season(season)
    url = (
        f"{WAYBACK_CDX}?url=www.fantasynerds.com/nfl/picks/{week}/*"
        f"&output=json&collapse=urlkey&fl=timestamp,original&limit=50"
    )
    resp = _fetch_with_retries(url)
    data = json.loads(resp)
    if len(data) <= 1:
        return []

    results = []
    for row in data[1:]:
        ts, orig = row
        # Extract game ID from URL like .../nfl/picks/1/259
        m = re.search(r'/nfl/picks/\d+/(\d+)$', orig)
        if not m:
            continue
        gid = int(m.group(1))
        if first_id <= gid <= last_id:
            results.append((ts, str(gid)))
    return results


def fetch_wayback_html(timestamp: str, original_url: str) -> str:
    """Fetch a page from the Wayback Machine using id_ (raw) mode."""
    url = f"{WAYBACK_BASE}/{timestamp}id_/{original_url}"
    return _fetch_with_retries(url)


def scrape_game_picks(week: int, fn_game_id: str) -> tuple[dict | None, list[dict]]:
    """
    Scrape expert picks for a single game.
    Returns (game_info, picks) where game_info has away/home teams.
    """
    url = f"{BASE_URL}/nfl/picks/{week}/{fn_game_id}"
    html = fetch_html(url)

    # Determine the two teams from the "Projected Score" line, which has
    # two teams_small2 images: <img src="/images/nfl/teams_small2/ATL.png" />
    proj_match = re.search(
        r'Projected Score.*?teams_small2/(\w+)\.png.*?teams_small2/(\w+)\.png',
        html, re.DOTALL,
    )
    if proj_match:
        away = normalize_team(proj_match.group(1).upper())
        home = normalize_team(proj_match.group(2).upper())
    else:
        away = None
        home = None

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
        # Alt text is an abbreviation (e.g. "ATL"), src has the filename
        pick_src = re.search(r'teams_small2/(\w+)\.png', cells[-1])
        if not pick_src:
            # Fallback: try any img alt or src
            pick_img = re.search(r'alt="(\w+)"', cells[-1])
            if pick_img:
                picked_team = normalize_team(pick_img.group(1).upper())
            else:
                continue
        else:
            picked_team = normalize_team(pick_src.group(1).upper())

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


def scrape_week_wayback(season: int, week: int) -> dict:
    """Scrape expert picks for a historical week via the Wayback Machine."""

    print("  Loading nflverse schedule for game ID lookup...")
    schedule_lookup = load_schedule(season, week)

    print("  Querying Wayback CDX for archived game pages...")
    archived = discover_wayback_game_ids(week, season)
    print(f"  Found {len(archived)} archived games for week {week}")

    if not archived:
        return {
            "season": season,
            "week": week,
            "season_type": "REG",
            "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sources": ["fantasynerds"],
            "games": [],
            "picks": [],
            "_experts": [],
        }

    all_games = []
    all_picks = []
    experts: dict[str, dict] = {}

    for ts, fn_id in archived:
        orig_url = f"https://www.fantasynerds.com/nfl/picks/{week}/{fn_id}"
        try:
            html = fetch_wayback_html(ts, orig_url)
        except Exception as e:
            print(f"  Wayback fetch failed for game {fn_id}: {e}")
            continue
        time.sleep(4)

        # Parse teams and picks using the same logic as scrape_game_picks
        proj_match = re.search(
            r'Projected Score.*?teams_small2/(\w+)\.png.*?teams_small2/(\w+)\.png',
            html, re.DOTALL,
        )
        if proj_match:
            away = normalize_team(proj_match.group(1).upper())
            home = normalize_team(proj_match.group(2).upper())
        else:
            away = None
            home = None

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
            pick_src = re.search(r'teams_small2/(\w+)\.png', cells[-1])
            if not pick_src:
                pick_img = re.search(r'alt="(\w+)"', cells[-1])
                if pick_img:
                    picked_team = normalize_team(pick_img.group(1).upper())
                else:
                    continue
            else:
                picked_team = normalize_team(pick_src.group(1).upper())
            if not picked_team:
                continue
            picks.append({
                "expert_name": name,
                "outlet": outlet,
                "pick": picked_team,
            })

        if not picks:
            print(f"  No picks parsed for game {fn_id}")
            continue

        game_info = None
        if away and home:
            game_info = {"away_team": away, "home_team": home}
        elif picks:
            picked_teams = list(dict.fromkeys(p["pick"] for p in picks))
            if len(picked_teams) == 2:
                game_info = {"away_team": picked_teams[0], "home_team": picked_teams[1]}

        if not game_info:
            continue

        team1 = game_info["away_team"]
        team2 = game_info["home_team"]
        pair = frozenset([team1, team2])
        game_id = schedule_lookup.get(pair)
        if not game_id:
            game_id = make_game_id(season, week, team1, team2)
            print(f"  Warning: no schedule match for {team1}/{team2}, using {game_id}")

        parts = game_id.split("_")
        away, home = parts[2], parts[3]

        all_games.append({
            "game_id": game_id,
            "away_team": away,
            "home_team": home,
        })

        for p in picks:
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

        print(f"  Game {fn_id}: {away} @ {home} — {len(picks)} picks")

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
        # For non-current weeks, scan for valid game IDs.
        # IDs are sequential but weeks vary in game count (13-16 during byes).
        # Estimate a starting point then scan a wide range.
        ref_ids = sorted(set(int(l[1]) for l in links))
        week_diff = page_week - week
        # Use 15 games/week as average (accounts for bye weeks with fewer)
        est_start = ref_ids[0] - int(week_diff * 15.5)

        fn_game_ids = []
        # Scan a wide window: up to 3 games/week drift over 18 weeks = ~54
        scan_start = est_start - 30
        scan_end = est_start + 30
        consecutive_misses = 0
        for cid in range(scan_start, scan_end):
            try:
                test_html = fetch_html(f"{BASE_URL}/nfl/picks/{week}/{cid}")
                if 'Expert Pick' in test_html:
                    fn_game_ids.append(str(cid))
                    consecutive_misses = 0
                else:
                    consecutive_misses += 1
            except Exception:
                consecutive_misses += 1
            time.sleep(0.3)
            # Stop after finding all games and hitting a gap
            if fn_game_ids and consecutive_misses >= 3:
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
    parser.add_argument("--wayback", action="store_true",
                        help="Scrape from Wayback Machine archives (for historical seasons)")
    return parser.parse_args()


def main():
    args = get_args()

    season = args.season or nfl.get_current_season()
    week = args.week or nfl.get_current_week()

    print(f"Scraping Fantasy Nerds picks for {season} Week {week}...")

    if args.wayback:
        print("  Using Wayback Machine for historical data...")
        data = scrape_week_wayback(season, week)
    else:
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
