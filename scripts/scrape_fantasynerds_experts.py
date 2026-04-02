#!/usr/bin/env python3
"""
Scrape historical expert picks from Fantasy Nerds via the Wayback Machine.

Expert pages at /nfl/picks/expert/{id}/{slug} contain all picks for the
current season in server-rendered HTML tables (one per week). The Wayback
Machine has snapshots for ~50 experts per season.

Strategy:
    1. Query Wayback CDX for all archived expert page snapshots
    2. For each season, pick the latest in-season snapshot per expert
    3. Fetch and parse each expert page for weekly picks
    4. Combine into per-week output files

Usage:
    python scripts/scrape_fantasynerds_experts.py --season 2022
    python scripts/scrape_fantasynerds_experts.py --season 2021 --season 2022
"""

import argparse
import json
import re
import time
from collections import defaultdict
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import nflreadpy as nfl

from normalize import normalize_team, make_game_id, slugify

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "cache" / "fantasynerds-experts"
WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
WAYBACK_BASE = "https://web.archive.org/web"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
}

# Map common full team names (as they appear on FN pages) to abbreviations
TEAM_CITY_MAP = {
    "Arizona": "ARI", "Atlanta": "ATL", "Baltimore": "BAL", "Buffalo": "BUF",
    "Carolina": "CAR", "Chicago": "CHI", "Cincinnati": "CIN", "Cleveland": "CLE",
    "Dallas": "DAL", "Denver": "DEN", "Detroit": "DET", "Green Bay": "GB",
    "Houston": "HOU", "Indianapolis": "IND", "Jacksonville": "JAX",
    "Kansas City": "KC", "Las Vegas": "LV", "LA Chargers": "LAC",
    "LA Rams": "LA", "Miami": "MIA", "Minnesota": "MIN",
    "New England": "NE", "New Orleans": "NO", "NY Giants": "NYG",
    "NY Jets": "NYJ", "Oakland": "LV", "Philadelphia": "PHI",
    "Pittsburgh": "PIT", "San Francisco": "SF", "Seattle": "SEA",
    "Tampa Bay": "TB", "Tennessee": "TEN", "Washington": "WAS",
}


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
            wait = 2 ** (attempt + 1) + 1
            print(f"      Retry {attempt + 1}/{max_retries - 1} after {wait}s ({e})")
            time.sleep(wait)


def load_schedule(season: int) -> dict[frozenset, dict]:
    """Load full nflverse schedule for a season.

    Returns mapping of frozenset({away, home}) -> {game_id, week, away, home}
    keyed per week.
    """
    sched = nfl.load_schedules(season)
    reg = sched.filter(sched["game_type"] == "REG")
    lookup = {}
    for row in reg.iter_rows(named=True):
        key = (row["week"], frozenset([row["away_team"], row["home_team"]]))
        lookup[key] = {
            "game_id": row["game_id"],
            "week": row["week"],
            "away_team": row["away_team"],
            "home_team": row["home_team"],
        }
    return lookup


def discover_expert_snapshots(seasons: list[int]) -> dict[int, list[tuple[str, str]]]:
    """Query CDX for all expert page snapshots.

    Returns {season: [(timestamp, original_url), ...]} with latest snapshot
    per expert per season.
    """
    print("Querying Wayback CDX for expert page archives...")
    url = (
        f"{WAYBACK_CDX}?url=www.fantasynerds.com/nfl/picks/expert/*"
        f"&output=json&fl=timestamp,original&limit=5000"
    )
    resp = _fetch_with_retries(url)
    data = json.loads(resp)
    print(f"  Found {len(data) - 1} total CDX entries")

    # Group by (season, expert_id), keeping the latest timestamp per expert
    best: dict[tuple[int, int], tuple[str, str]] = {}

    for row in data[1:]:
        ts, orig = row
        m = re.search(r'/expert/(\d+)', orig)
        if not m:
            continue
        eid = int(m.group(1))
        year = int(ts[:4])
        month = int(ts[4:6])

        # Map timestamp to NFL season
        if month >= 9:
            season = year
        elif month <= 2:
            season = year - 1
        else:
            continue  # offseason

        if season not in seasons:
            continue

        key = (season, eid)
        if key not in best or ts > best[key][0]:
            best[key] = (ts, orig)

    # Group by season
    result: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for (season, _eid), (ts, orig) in sorted(best.items()):
        result[season].append((ts, orig))

    for s in sorted(result):
        print(f"  {s} season: {len(result[s])} experts")

    return dict(result)


def parse_expert_page(html: str) -> tuple[str | None, str | None, list[dict]]:
    """Parse an expert page's HTML for picks.

    Returns (expert_name, outlet, picks) where each pick is:
        {week: int, away: str, home: str, pick: str}
    """
    # Extract expert name and outlet from the H1 tag specifically
    # H1 format: "NFL Picks - Expert: <span class="smurf">Name, Outlet</span>"
    heading = re.search(
        r'<h1[^>]*>.*?Expert.*?<span[^>]*>(.*?)</span>', html, re.DOTALL
    )
    expert_name = None
    outlet = None
    if heading:
        parts = heading.group(1).strip()
        # Format is "Name, Outlet" e.g. "Matt Bowen, ESPN"
        if ", " in parts:
            expert_name, outlet = parts.rsplit(", ", 1)
        else:
            expert_name = parts

    # Find all tables
    tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL)

    # Find week labels — they appear as h4 headings before each table
    week_labels = re.findall(r'<h4[^>]*>.*?Week\s+(\d+)\s+Picks.*?</h4>', html, re.DOTALL)
    # Deduplicate in order
    seen = set()
    weeks_ordered = []
    for w in week_labels:
        if w not in seen:
            seen.add(w)
            weeks_ordered.append(int(w))

    picks = []
    for i, table in enumerate(tables):
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table, re.DOTALL)
        for row in rows:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            if len(cells) < 3:
                continue

            cell_texts = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]

            # Detect format: 4+ columns with week number = single-table format
            # 3 columns = multi-table format (one table per week)
            if len(cells) >= 4 and cell_texts[0].isdigit():
                # Single-table format: Week, Game, Prediction, Correct
                week = int(cell_texts[0])
                game_text = cell_texts[1]
                pick_text = cell_texts[2]
            else:
                # Multi-table format: Game, Prediction, Correct
                week = weeks_ordered[i] if i < len(weeks_ordered) else i + 1
                game_text = cell_texts[0]
                pick_text = cell_texts[1]

            if '@' not in game_text or not pick_text:
                continue

            # Parse "CAR @ TB" or "NY Giants @ Tampa Bay"
            parts = re.split(r'\s+@\s+', game_text)
            if len(parts) != 2:
                continue

            away_raw, home_raw = parts[0].strip(), parts[1].strip()

            # Normalize team names — try as abbreviation first, then city name
            away = normalize_team(away_raw) or TEAM_CITY_MAP.get(away_raw)
            home = normalize_team(home_raw) or TEAM_CITY_MAP.get(home_raw)

            if not away or not home:
                continue

            pick = normalize_team(pick_text) or TEAM_CITY_MAP.get(pick_text)
            if not pick:
                continue

            picks.append({
                "week": week,
                "away": away,
                "home": home,
                "pick": pick,
            })

    return expert_name, outlet, picks


def _cache_path(timestamp: str, orig_url: str) -> Path:
    """Return a local cache path for a Wayback page."""
    # Extract expert ID and slug from URL
    m = re.search(r'/expert/(\d+)(?:/(\w+))?', orig_url)
    if m:
        eid = m.group(1)
        slug = m.group(2) or "unknown"
        return CACHE_DIR / f"{timestamp}_{eid}_{slug}.html"
    return CACHE_DIR / f"{timestamp}.html"


def fetch_or_cache(timestamp: str, orig_url: str) -> str:
    """Fetch from Wayback, or return cached HTML if available."""
    cache = _cache_path(timestamp, orig_url)
    if cache.exists():
        return cache.read_text()

    url = f"{WAYBACK_BASE}/{timestamp}id_/{orig_url}"
    html = _fetch_with_retries(url)

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(html)
    return html


def scrape_season(season: int, snapshots: list[tuple[str, str]]) -> dict[int, dict]:
    """Scrape all expert pages for a season from Wayback.

    Returns {week: {games: [...], picks: [...]}} for each week with data.
    """
    print(f"\nLoading nflverse schedule for {season}...")
    schedule = load_schedule(season)

    weeks_data: dict[int, dict] = {}
    for week in range(1, 19):
        weeks_data[week] = {"games": {}, "picks": []}

    experts_scraped = 0
    total_picks = 0

    for ts, orig_url in snapshots:
        try:
            html = fetch_or_cache(ts, orig_url)
        except Exception as e:
            print(f"    Failed: {orig_url} ({e})")
            continue
        time.sleep(4)

        expert_name, outlet, picks = parse_expert_page(html)
        if not picks or not expert_name:
            continue

        experts_scraped += 1
        slug = slugify(expert_name)
        print(f"  {expert_name} ({outlet}): {len(picks)} picks across {len(set(p['week'] for p in picks))} weeks")

        for p in picks:
            week = p["week"]
            if week < 1 or week > 18:
                continue

            # Look up canonical game ID
            pair = frozenset([p["away"], p["home"]])
            sched_key = (week, pair)
            game_info = schedule.get(sched_key)

            if game_info:
                game_id = game_info["game_id"]
                away = game_info["away_team"]
                home = game_info["home_team"]
            else:
                game_id = make_game_id(season, week, p["away"], p["home"])
                away = p["away"]
                home = p["home"]

            # Add game if not seen
            if game_id not in weeks_data[week]["games"]:
                weeks_data[week]["games"][game_id] = {
                    "game_id": game_id,
                    "away_team": away,
                    "home_team": home,
                }

            weeks_data[week]["picks"].append({
                "expert": slug,
                "expert_name": expert_name,
                "source": "fantasynerds",
                "outlet": outlet or "Unknown",
                "game_id": game_id,
                "pick": p["pick"],
                "pick_type": "straight_up",
            })
            total_picks += 1

    print(f"\n  {experts_scraped} experts scraped, {total_picks} total picks")
    return weeks_data


def main():
    parser = argparse.ArgumentParser(
        description="Scrape historical Fantasy Nerds picks via Wayback Machine expert pages"
    )
    parser.add_argument(
        "--season", type=int, action="append", required=True,
        help="Season(s) to scrape (can specify multiple)",
    )
    args = parser.parse_args()
    seasons = args.season

    # Discover available snapshots
    snapshots_by_season = discover_expert_snapshots(seasons)

    for season in seasons:
        if season not in snapshots_by_season:
            print(f"\nNo Wayback snapshots found for {season} season")
            continue

        print(f"\n{'='*60}")
        print(f"Scraping {season} season ({len(snapshots_by_season[season])} experts)")
        print(f"{'='*60}")

        weeks_data = scrape_season(season, snapshots_by_season[season])

        # Write per-week files
        picks_dir = ROOT / "data" / "picks" / str(season)
        picks_dir.mkdir(parents=True, exist_ok=True)

        for week in range(1, 19):
            wd = weeks_data[week]
            if not wd["picks"]:
                continue

            out = {
                "season": season,
                "week": week,
                "season_type": "REG",
                "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "sources": ["fantasynerds"],
                "games": list(wd["games"].values()),
                "picks": wd["picks"],
            }

            out_path = picks_dir / f"week-{week}-fantasynerds.json"
            out_path.write_text(json.dumps(out, indent=2) + "\n")
            print(f"  Week {week}: {len(wd['picks'])} picks across {len(wd['games'])} games -> {out_path}")


if __name__ == "__main__":
    main()
