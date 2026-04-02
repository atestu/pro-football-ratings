# NFL Expert Picks Tracker

## Goal

Track every NFL "expert" pick from major media outlets, compare against actual
game results, and publish accuracy leaderboards. Hold the pundits accountable.

## Architecture

GitHub Actions-powered, zero-infrastructure approach:

```
Cron (weekly)          Cron (post-MNF)         GitHub Pages
     |                      |                       |
 Scrape picks          Fetch results           Static site
     |                      |                       |
 Store as JSON  --->   Score & grade  --->    Leaderboard
 (committed)           (committed)            (auto-deploy)
```

No database. No server. All data lives as JSON in the repo.
Free to run on GitHub Actions (public repo = 2,000 min/month).

---

## Data Sources

### Expert Picks

| Source | Method | Coverage | Priority |
|--------|--------|----------|----------|
| **ESPN talentpicks API** | JSON fetch (no auth) | ~10-14 ESPN analysts | P0 |
| **NFLPickWatch** (`?text=1`) | Light HTML parse | 100+ experts across outlets | P1 |
| **CBS Sports** | HTML scrape (server-rendered) | ~8-10 CBS writers | P2 |

ESPN talentpicks endpoint:
```
https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/{YEAR}/types/2/weeks/{WEEK}/talentpicks?limit=100
```

This is undocumented and could break, so NFLPickWatch is the fallback/complement.

### Game Results

| Source | Method | Notes |
|--------|--------|-------|
| **nflverse schedules** | CSV download | Canonical game results, free |
| **ESPN scoreboard API** | JSON fetch | Faster updates, undocumented |

nflverse schedules URL:
```
https://github.com/nflverse/nfldata/raw/master/data/games.csv
```

---

## Data Model

All stored as JSON files committed to the repo.

### `data/picks/{season}/week-{week}.json`

```json
{
  "season": 2026,
  "week": 1,
  "season_type": "REG",
  "scraped_at": "2026-09-10T12:00:00Z",
  "sources": ["espn_talentpicks", "pickwatch"],
  "games": [
    {
      "game_id": "2026_01_KC_BAL",
      "away_team": "KC",
      "home_team": "BAL",
      "kickoff": "2026-09-10T20:20:00Z"
    }
  ],
  "picks": [
    {
      "expert": "dan-graziano",
      "expert_name": "Dan Graziano",
      "source": "espn_talentpicks",
      "outlet": "ESPN",
      "game_id": "2026_01_KC_BAL",
      "pick": "BAL",
      "pick_type": "straight_up"
    }
  ]
}
```

### `data/results/{season}/week-{week}.json`

```json
{
  "season": 2026,
  "week": 1,
  "games": [
    {
      "game_id": "2026_01_KC_BAL",
      "away_team": "KC",
      "home_team": "BAL",
      "away_score": 24,
      "home_score": 27,
      "winner": "BAL"
    }
  ]
}
```

### `data/scores/{season}/leaderboard.json`

```json
{
  "season": 2026,
  "through_week": 5,
  "experts": [
    {
      "expert": "dan-graziano",
      "expert_name": "Dan Graziano",
      "outlet": "ESPN",
      "correct": 52,
      "total": 75,
      "accuracy": 0.693,
      "weekly": [
        { "week": 1, "correct": 10, "total": 16 }
      ]
    }
  ]
}
```

### `data/experts.json`

Master registry of all tracked experts with slugs, names, outlets, and source
IDs for deduplication across sources.

---

## GitHub Actions Workflows

### 1. `scrape-picks.yml` (P0)

- **Trigger:** Cron — Wednesday 12:00 UTC during NFL season (Sep-Feb)
- **Also:** Manual dispatch (for backfilling / testing)
- **Steps:**
  1. Fetch ESPN talentpicks API for current week
  2. Scrape NFLPickWatch text mode
  3. Normalize team abbreviations, deduplicate experts across sources
  4. Commit `data/picks/{season}/week-{week}.json`

### 2. `fetch-results.yml` (P0)

- **Trigger:** Cron — Tuesday 08:00 UTC (after Monday Night Football)
- **Also:** Manual dispatch
- **Steps:**
  1. Download nflverse games.csv (or hit ESPN scoreboard API)
  2. Extract results for the completed week
  3. Commit `data/results/{season}/week-{week}.json`

### 3. `score-experts.yml` (P0)

- **Trigger:** On push to `data/results/`
- **Also:** Manual dispatch
- **Steps:**
  1. Load picks and results for the week
  2. Grade each expert (correct/incorrect per game)
  3. Update cumulative leaderboard
  4. Commit `data/scores/{season}/leaderboard.json`

### 4. `deploy-site.yml` (P1)

- **Trigger:** On push to `data/scores/`
- **Steps:**
  1. Build static site from leaderboard JSON
  2. Deploy to GitHub Pages

### 5. `backfill.yml` (P2)

- **Trigger:** Manual dispatch with season/week inputs
- **Steps:**
  1. Fetch historical picks and results for a given week
  2. Run scoring pipeline

---

## Project Structure

```
nfl-predictions/
  .github/
    workflows/
      scrape-picks.yml
      fetch-results.yml
      score-experts.yml
      deploy-site.yml
      backfill.yml
  scripts/
    scrape-espn-picks.js       # ESPN talentpicks API fetcher
    scrape-pickwatch.js        # NFLPickWatch text-mode parser
    fetch-results.js           # Game results fetcher
    score-experts.js           # Grading + leaderboard builder
    normalize.js               # Team abbrev mapping, dedup
    nfl-weeks.js               # Season schedule / week detection
  data/
    experts.json
    picks/{season}/week-{week}.json
    results/{season}/week-{week}.json
    scores/{season}/leaderboard.json
  site/                        # Static leaderboard site (P1)
    index.html
    style.css
    app.js
  docs/
    plans/
  package.json
  README.md
```

---

## Tech Stack

- **Runtime:** Node.js 20
- **HTTP:** Built-in `fetch()` (no dependencies for API calls)
- **HTML parsing:** `cheerio` (only needed for Pickwatch scraping)
- **CI/CD:** GitHub Actions
- **Hosting:** GitHub Pages
- **Frontend:** Vanilla HTML/CSS/JS (no framework needed for a leaderboard)

Minimal dependencies. No database, no build tools, no framework.

---

## Implementation Phases

### Phase 1: Core Pipeline (MVP)

1. ESPN talentpicks scraper script
2. Game results fetcher (nflverse CSV)
3. Scoring/grading script
4. GitHub Actions workflows (scrape, results, score)
5. Basic README

Deliverable: automated weekly data collection and scoring, all in JSON.

### Phase 2: More Sources + Site

6. NFLPickWatch scraper
7. Expert deduplication across sources
8. Static leaderboard site on GitHub Pages
9. Deploy workflow

Deliverable: multi-source picks with a public leaderboard.

### Phase 3: Historical + Polish

10. Backfill workflow for past seasons
11. Per-expert detail pages
12. Season-over-season trends
13. "Best/worst week" highlights

---

## Open Questions

- **ATS vs straight-up:** ESPN talentpicks does ATS. Pickwatch does both.
  Start with straight-up (simpler) or ATS (more interesting)?
- **Expert identity:** Same person may appear on ESPN and Pickwatch with
  slightly different names. Need a dedup/alias strategy.
- **API stability:** ESPN's undocumented API could change. How much do we
  invest in fallback strategies vs. just fixing when it breaks?
- **Bye weeks / international games:** Some weeks have fewer games.
  Scoring should be percentage-based, not raw count.
- **Playoffs:** Include postseason picks or regular season only?

---

## Prior Art / References

- [thomaspryor/Broadwayscore](https://github.com/thomaspryor/Broadwayscore) —
  GitHub Actions-powered review aggregator (140 workflows, inspiration for approach)
- [thmsdrew/pypicks](https://github.com/thmsdrew/pypicks) — Python Pickwatch scraper
- [stevekrenzel/pick-ems](https://github.com/stevekrenzel/pick-ems) — Playwright ESPN scraper
- [gtonic/nfl_mcp](https://github.com/gtonic/nfl_mcp) — CBS Sports picks via API
- [nflverse](https://github.com/nflverse) — Canonical open NFL data (game results)
- [nntrn's ESPN API gist](https://gist.github.com/nntrn/ee26cb2a0716de0947a0a4e9a157bc1c) —
  Undocumented ESPN API endpoint catalog
