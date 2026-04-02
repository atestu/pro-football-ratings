# NFL Expert Picks Tracker

Track NFL media expert picks, compare against actual results, and rank the pundits by accuracy. Hold the pundits accountable.

## How It Works

```
Cron (Wednesday)        Cron (Tuesday)          GitHub Pages (future)
     |                      |                       |
 Scrape picks          Fetch results           Static site
 (ESPN API)            (nflreadpy)                  |
     |                      |                  Leaderboard
 Store as JSON  --->   Score & grade  --->    (auto-deploy)
 (committed)           (committed)
```

All data lives as JSON in the repo. No database, no server. Automated via GitHub Actions.

## Data Sources

| Source | Type | Notes |
|--------|------|-------|
| ESPN talentpicks API | Expert picks | ~10-14 ESPN analysts per week |
| nflverse (via nflreadpy) | Game results | Canonical NFL schedule data |

## Setup

```bash
pip install -r requirements.txt
```

Requires Python 3.12+.

## Usage

### Scrape expert picks
```bash
python scripts/scrape_espn_picks.py --season 2024 --week 1
```

### Fetch game results
```bash
python scripts/fetch_results.py --season 2024 --week 1
```

### Score experts and build leaderboard
```bash
# Score a specific week
python scripts/score_experts.py --season 2024 --week 1

# Score all available weeks for a season
python scripts/score_experts.py --season 2024
```

All scripts auto-detect the current season/week if `--season` and `--week` are omitted.

## Data Layout

```
data/
  experts.json                     # Master expert registry
  picks/{season}/week-{week}.json  # Raw expert picks
  results/{season}/week-{week}.json # Game outcomes
  scores/{season}/leaderboard.json  # Accuracy rankings
```

## Automation

Three GitHub Actions workflows run automatically during the NFL season (Sep-Feb):

- **Scrape Picks** (Wednesday 12:00 UTC) - Fetches expert picks for the current week
- **Fetch Results** (Tuesday 08:00 UTC) - Fetches game results after Monday Night Football, then scores experts
- **Score Experts** - Also triggered when results data is pushed

All workflows support manual dispatch with custom season/week inputs.

## Architecture

See [docs/plans/nfl-expert-picks-tracker.md](docs/plans/nfl-expert-picks-tracker.md) for the full architecture plan.
