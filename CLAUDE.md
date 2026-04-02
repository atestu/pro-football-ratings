# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NFL Expert Picks Tracker: scrapes expert picks from media outlets, compares against game results, and builds accuracy leaderboards. Zero-infrastructure -- all data is committed JSON, automated via GitHub Actions.

## Commands

```bash
# Run any script (handles Python version + deps automatically)
uv run scripts/scrape_espn_picks.py --season 2025 --week 1
uv run scripts/scrape_fantasynerds.py --season 2025 --week 1
uv run scripts/fetch_results.py --season 2025 --week 1
uv run scripts/score_experts.py --season 2025          # all weeks
uv run scripts/score_experts.py --season 2025 --week 1  # single week
```

All scripts accept `--season` and `--week` (both optional, auto-detected from current date via `nflreadpy.get_current_season()`/`get_current_week()`).

## Architecture

**Pipeline flow:** Scrape picks -> Fetch results -> Score experts -> Leaderboard JSON

**Two independent pick scrapers:**
- `scrape_espn_picks.py` -- Parses `window['__espnfitt__']` embedded JSON from ESPN picks HTML page. Outputs `data/picks/{season}/week-{week}.json`.
- `scrape_fantasynerds.py` -- Scrapes fantasynerds.com (aggregates ESPN, CBS, Yahoo, FanDuel, DraftKings, etc.). Outputs `data/picks/{season}/week-{week}-fantasynerds.json`. Teams are parsed from the "Projected Score" line on each game page. The index page (`/nfl/picks`) only shows the current week's game IDs; historical weeks require scanning sequential IDs. Requires nflverse schedule lookup to get canonical away/home ordering for game IDs.

**Results:** `fetch_results.py` uses `nflreadpy.load_schedules()` which returns Polars DataFrames from nflverse parquet files. No CSV parsing.

**Scoring:** `score_experts.py` reads picks + results JSON files, compares picks against winners, builds cumulative leaderboard. Ties are excluded from totals.

**Shared utilities in `scripts/normalize.py`:**
- `normalize_team()` -- maps source-specific abbreviations to nflverse canonical form (e.g., `LAR` -> `LA`, `WSH` -> `WAS`, `JAC` -> `JAX`)
- `make_game_id()` -- format: `{season}_{week:02d}_{away}_{home}`
- `slugify()` -- expert name to URL slug

## Key Conventions

- **Team abbreviations** follow nflverse convention. ESPN uses `LAR`/`WSH`, Fantasy Nerds uses `JAC`/`LAR` -- always normalize through `normalize_team()`.
- **Game IDs** match nflverse format: `2025_01_BAL_KC` (away first, week zero-padded). The nflverse schedule is the source of truth for away/home ordering.
- **Expert slugs** are derived from display names via `slugify()` and used as stable identifiers across weeks.
- **Pick files per source**: ESPN picks go in `week-{N}.json`, Fantasy Nerds in `week-{N}-fantasynerds.json`. The scorer currently only reads the ESPN files (`week-{N}.json`).
- **No external HTTP libraries** -- scrapers use `urllib.request` only. `nflreadpy` (which depends on Polars) is the sole heavy dependency.

## Data Sources Gotcha

The ESPN Core API (`sports.core.api.espn.com/v2/.../talentpicks`) is **not reliable** for historical picks -- it overwrites pick data with game winners after results are in. The working approach parses the ESPN picks webpage HTML instead.
