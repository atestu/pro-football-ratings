# Pro Football Ratings

Track NFL media expert picks, compare against actual results, and rate the pickers against a Vegas baseline. Hold the pundits accountable. Future home of [profootballratings.com](https://profootballratings.com).

## How It Works

```
Cron (Thursday)         Cron (Tuesday)          GitHub Pages (future)
     |                      |                       |
 Scrape picks          Fetch results           Static site
 (ESPN, NFL, PFT)      (nflreadpy)                  |
     |                      |                  Leaderboard
 Store as JSON  --->   Score & grade  --->    (auto-deploy)
 (committed)           (committed)
                            |
                       Rate experts  --->   Cross-season ratings
                       (vs Vegas baseline)  (letter grades A+ - F)
```

All data lives as JSON in the repo. No database, no server. Automated via GitHub Actions.

## Data Sources

| Source | Type | Notes |
|--------|------|-------|
| ESPN picks page | Expert picks | ~10-14 ESPN analysts per week. The page is behind an AWS WAF challenge, so the scraper falls back to ESPN's core API |
| Fantasy Nerds | Expert picks | ~26-35 experts from ESPN, CBS, Yahoo, FanDuel, DraftKings, etc. In the scheduled scrape on a best-effort basis (may 403-block datacenter IPs); falls back to manual runs |
| NFL.com | Expert picks | ~5 NFL.com analysts per week |
| ProFootballTalk | Expert picks | ~2 PFT analysts per week |
| nflverse (via nflreadpy) | Game results + schedule | Canonical NFL data (scores, spreads, game dates) |

## Setup

```bash
uv sync
```

Requires Python 3.12+.

## Usage

### Scrape expert picks
```bash
uv run scripts/scrape_espn_picks.py --season 2025 --week 1
uv run scripts/scrape_fantasynerds.py --season 2025 --week 1
```

### Fetch game results
```bash
uv run scripts/fetch_results.py --season 2025 --week 1
```

### Score experts and build leaderboard
```bash
# Score a specific week
uv run scripts/score_experts.py --season 2025 --week 1

# Score all available weeks for a season
uv run scripts/score_experts.py --season 2025
```

### Cross-season expert ratings
```bash
# Rate all experts across all available seasons (2015-2025)
uv run scripts/rate_experts.py

# Validate historical pick data integrity
uv run scripts/rate_experts.py --validate

# Tune parameters
uv run scripts/rate_experts.py --half-life 78 --min-picks 50
```

Each expert is scored against a "pick the Vegas favorite every game" baseline, weighted by recency (exponential decay). Scores map to letter grades (A+ through F). Only experts with 100+ picks qualify for a rating.

All scripts auto-detect the current season/week if `--season` and `--week` are omitted.

## Data Layout

```
data/
  experts.json                                # Master expert registry
  picks/{season}/week-{week}.json             # ESPN expert picks
  picks/{season}/week-{week}-fantasynerds.json # Fantasy Nerds expert picks
  picks/{season}/week-{week}-nfl.json         # NFL.com expert picks
  picks/{season}/week-{week}-pft.json         # ProFootballTalk expert picks
  results/{season}/week-{week}.json           # Game outcomes
  scores/{season}/leaderboard.json            # Per-season accuracy rankings
  scores/ratings.json                         # Cross-season expert ratings
```

## Automation

Three GitHub Actions workflows run automatically during the NFL season (the cron checks skip March-August, and the scrapers skip postseason weeks):

- **Scrape Picks** (Thursday 16:00 UTC / noon ET) - Fetches expert picks for the current week once all outlets have published, hours before Thursday Night Football kicks off. A late NFL.com or PFT article doesn't block committing the other outlets' picks
- **Fetch Results** (Tuesday 08:00 UTC) - Fetches game results after Monday Night Football, then scores experts and refreshes cross-season ratings
- **Score Experts** - Also triggered when results data is pushed

All workflows support manual dispatch with custom season/week inputs.

## Architecture

See [docs/plans/nfl-expert-picks-tracker.md](docs/plans/nfl-expert-picks-tracker.md) for the full architecture plan.
