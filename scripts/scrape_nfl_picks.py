#!/usr/bin/env python3
"""
Scrape expert picks from NFL.com.

NFL.com publishes weekly expert picks articles at:
    https://www.nfl.com/news/nfl-picks-week-{N}-{YEAR}-nfl-season

The page is server-rendered HTML. Each game section is preceded by a MONEYLINE
line identifying the two teams, followed by a table with expert picks.

Usage:
    python scripts/scrape_nfl_picks.py [--season 2025] [--week 1]
"""

import argparse
import json
import re
import time
from html.parser import HTMLParser
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

# Mapping from first names in table headers to full expert names
EXPERT_MAP = {
    "Ali": "Ali Bhanpuri",
    "Brooke": "Brooke Cersosimo",
    "Dan": "Dan Parr",
    "Gennaro": "Gennaro Filice",
    "Tom": "Tom Blair",
}


class TableParser(HTMLParser):
    """Minimal HTML table parser that extracts rows of cell text."""

    def __init__(self):
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell: str = ""

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._in_table = True
            self._current_table = []
        elif tag == "tr" and self._in_table:
            self._in_row = True
            self._current_row = []
        elif tag in ("td", "th") and self._in_row:
            self._in_cell = True
            self._current_cell = ""

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._in_cell:
            self._in_cell = False
            self._current_row.append(self._current_cell.strip())
        elif tag == "tr" and self._in_row:
            self._in_row = False
            if self._current_row:
                self._current_table.append(self._current_row)
        elif tag == "table" and self._in_table:
            self._in_table = False
            if self._current_table:
                self.tables.append(self._current_table)

    def handle_data(self, data):
        if self._in_cell:
            self._current_cell += data


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


def parse_moneyline_teams(line: str) -> tuple[str, str]:
    """Extract two team nicknames from a MONEYLINE line.

    Example: 'MONEYLINE: Vikings -122 | Bears +102'
    Returns: ('Vikings', 'Bears')
    """
    # Strip the MONEYLINE: prefix
    after_colon = line.split(":", 1)[1].strip()
    # Split on the pipe separator
    parts = after_colon.split("|")
    if len(parts) != 2:
        raise ValueError(f"Expected 2 teams in MONEYLINE line, got {len(parts)}: {line}")

    # Each part is like "Vikings -122" or "Bears +102"
    # Extract the team name (first word(s) before the number)
    teams = []
    for part in parts:
        part = part.strip()
        # Match everything before the last number (with optional sign)
        m = re.match(r"(.+?)\s+[+-]?\d+", part)
        if m:
            teams.append(m.group(1).strip())
        else:
            # Fallback: just take the first word
            teams.append(part.split()[0].strip())

    return teams[0], teams[1]


def scrape_picks(season: int, week: int) -> dict:
    """Scrape all expert picks for a given week from NFL.com."""
    url = f"https://www.nfl.com/news/nfl-picks-week-{week}-{season}-nfl-season"
    print(f"Fetching: {url}")
    html = fetch_html(url)

    # Load schedule for canonical game IDs
    print("  Loading nflverse schedule for game ID lookup...")
    schedule_lookup = load_schedule(season, week)

    # Parse all tables from the HTML
    parser = TableParser()
    parser.feed(html)

    # Find all MONEYLINE lines and their positions in the HTML.
    # The HTML wraps the label in <strong> tags:
    #   <strong>MONEYLINE:</strong> Vikings -122 | Bears +102
    # or <strong>MONEYLINE: </strong>Vikings -122 | Bears +102
    moneyline_pattern = re.compile(
        r"<strong>\s*MONEYLINE\s*:?\s*</strong>\s*:?\s*(.*?)</li>",
        re.IGNORECASE | re.DOTALL,
    )
    moneyline_matches = list(moneyline_pattern.finditer(html))
    print(f"  Found {len(moneyline_matches)} MONEYLINE lines")

    # For each MONEYLINE, find the next <table> that follows it
    # Strategy: record position of each MONEYLINE and each <table>,
    # then pair each MONEYLINE with the next table after it
    table_starts = [m.start() for m in re.finditer(r"<table", html, re.IGNORECASE)]

    games: dict[str, dict] = {}
    all_picks: list[dict] = []
    experts: dict[str, dict] = {}

    for ml_match in moneyline_matches:
        ml_pos = ml_match.start()
        # Group 1 contains the team/odds text after the <strong> label
        ml_text = re.sub(r"<[^>]+>", "", ml_match.group(1)).strip()

        # Parse team names from the odds text (e.g. "Vikings -122 | Bears +102")
        try:
            nick1, nick2 = parse_moneyline_teams(":" + ml_text)
        except ValueError as e:
            print(f"  Warning: {e}")
            continue

        # Resolve nicknames to abbreviations
        try:
            team1 = normalize_team_name(nick1)
        except KeyError:
            raise RuntimeError(f"Unrecognized team name from MONEYLINE: '{nick1}'")
        try:
            team2 = normalize_team_name(nick2)
        except KeyError:
            raise RuntimeError(f"Unrecognized team name from MONEYLINE: '{nick2}'")

        # Find the canonical game ID via schedule lookup
        pair = frozenset([team1, team2])
        game_id = schedule_lookup.get(pair)
        if not game_id:
            game_id = make_game_id(season, week, team1, team2)
            print(f"  Warning: no schedule match for {team1}/{team2}, using {game_id}")

        # Parse away/home from game_id
        parts = game_id.split("_")
        away, home = parts[2], parts[3]

        games[game_id] = {
            "game_id": game_id,
            "away_team": away,
            "home_team": home,
        }

        # Find the next table after this MONEYLINE
        next_table_idx = None
        for i, ts in enumerate(table_starts):
            if ts > ml_pos:
                next_table_idx = i
                break

        if next_table_idx is None or next_table_idx >= len(parser.tables):
            print(f"  Warning: no table found after MONEYLINE for {nick1}/{nick2}")
            continue

        table = parser.tables[next_table_idx]

        # The first row should be headers with expert first names
        if len(table) < 2:
            print(f"  Warning: table too small for {game_id}")
            continue

        header_row = table[0]

        # Find expert columns by matching first names
        expert_columns: list[tuple[int, str, str]] = []  # (col_index, slug, full_name)
        for col_idx, cell_text in enumerate(header_row):
            cell_text = cell_text.strip()
            if cell_text in EXPERT_MAP:
                full_name = EXPERT_MAP[cell_text]
                expert_columns.append((col_idx, slugify(full_name), full_name))

        # Verify all expected experts are present
        found_names = {cell.strip() for cell in header_row if cell.strip() in EXPERT_MAP}
        for expected_name in EXPERT_MAP:
            if expected_name not in found_names:
                raise RuntimeError(
                    f"Expected expert '{expected_name}' not found in table header "
                    f"for game {game_id}. Header: {header_row}"
                )

        # Parse pick rows - there should be one data row with picks
        for row in table[1:]:
            for col_idx, slug, full_name in expert_columns:
                if col_idx >= len(row):
                    continue
                cell = row[col_idx].strip()
                if not cell:
                    continue

                # Cell format: "Team Score-Score" e.g. "Eagles 27-20"
                # Extract the team name (everything before the score)
                pick_match = re.match(r"(.+?)\s+\d+\s*-\s*\d+", cell)
                if not pick_match:
                    # Try without score (just team name)
                    pick_match = re.match(r"(\S+)", cell)
                if not pick_match:
                    continue

                picked_nick = pick_match.group(1).strip()
                try:
                    picked_team = normalize_team_name(picked_nick)
                except KeyError:
                    print(f"  Warning: unrecognized pick team '{picked_nick}' in {game_id}")
                    continue

                experts[slug] = {
                    "expert": slug,
                    "expert_name": full_name,
                    "source": "nfl_com",
                    "outlet": "NFL.com",
                }

                all_picks.append({
                    "expert": slug,
                    "expert_name": full_name,
                    "source": "nfl_com",
                    "outlet": "NFL.com",
                    "game_id": game_id,
                    "pick": picked_team,
                    "pick_type": "straight_up",
                })

    return {
        "season": season,
        "week": week,
        "season_type": "REG",
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": ["nfl_com"],
        "games": list(games.values()),
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
    parser = argparse.ArgumentParser(description="Scrape NFL.com expert picks")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=None)
    return parser.parse_args()


def main():
    args = get_args()

    season = args.season or nfl.get_current_season()
    week = args.week or nfl.get_current_week()

    print(f"Scraping NFL.com picks for {season} Week {week}...")

    data = scrape_picks(season, week)
    new_experts = data.pop("_experts")

    picks_dir = ROOT / "data" / "picks" / str(season)
    picks_dir.mkdir(parents=True, exist_ok=True)

    picks_path = picks_dir / f"week-{week}-nfl.json"
    picks_path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Wrote {len(data['picks'])} picks across {len(data['games'])} games to {picks_path}")

    update_experts_registry(new_experts)
    print("Done.")


if __name__ == "__main__":
    main()
