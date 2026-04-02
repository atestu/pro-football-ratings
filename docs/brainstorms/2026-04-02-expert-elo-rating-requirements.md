---
date: 2026-04-02
topic: expert-rating
---

# Expert Rating System

## Problem Frame

The current leaderboard resets every season — a consistently strong expert over 4 seasons looks identical to a one-season wonder. There is no durable measure of expert quality that accounts for longevity, consistency, or whether an expert actually adds value beyond naive strategies. This feature creates a cross-season rating system inspired by FiveThirtyEight's pollster grades: a composite score reflecting both predictive skill and track record, surfaced as a letter grade with a numerical score.

## Requirements

**Rating Methodology**

- R1. Each expert receives a numerical rating score that blends two signals: (a) accuracy relative to a "pick the Vegas favorite every game" baseline, and (b) consistency of that performance across seasons.
- R2. The Vegas favorite for each game is determined from the existing spread data in results files (positive spread = home favorite, negative spread = away favorite). Games with spread_line = 0 (pick-em) are excluded from the baseline comparison, as there is no Vegas favorite.
- R3. Each pick's contribution to the rating decays continuously based on age, using the actual game date (available via `kickoff` in picks files or nflverse schedule). More recent picks always carry more weight. There is no special decay at season boundaries.
- R4. Only straight-up picks are used in the rating. The existing ATS scoring is not incorporated since all scraped picks are straight-up picks, not intentional spread picks.

**Qualification & Participation**

- R5. An expert must have a minimum cumulative pick count (threshold TBD, placeholder 100+; see Outstanding Questions for calibration) before receiving a rating. Experts below this threshold are marked "provisional" or unrated.
- R6. All available seasons of data (2021-2025) are used, with older seasons weighted less due to decay. Results files exist for all 5 seasons. Leaderboard scoring for 2021-2023 must be generated (via `score_experts.py`) as a prerequisite.
- R7. Experts with no picks in a given season (due to source coverage gaps) are not penalized — decay applies naturally since they simply have no recent picks to contribute weight.

**Output & Presentation**

- R8. Each rated expert receives a letter grade (A+ through F) derived from their numerical score, using defined score-to-grade thresholds.
- R9. A new cross-season rating output file is produced (e.g., `data/scores/ratings.json`), separate from the existing per-season `leaderboard.json`. It contains the letter grade (primary) and numerical score (secondary) for all qualified experts. The existing per-season leaderboard is not modified.

## Success Criteria

- An expert who consistently picks at 68%+ SU accuracy across 3+ seasons rates higher than one who hit 75% in a single season
- An expert who merely picks the Vegas favorite every game lands around a C grade (baseline performance)
- The rating meaningfully differentiates the top tier from the middle of the pack — not everyone clusters in the same grade bucket
- Ratings are reproducible: running the script twice on the same data produces identical output

## Scope Boundaries

- No ATS component in the rating (picks are straight-up only; ATS scoring would be measuring noise)
- No upset bonus or variable game weighting — picks are weighted only by recency (R3 continuous decay), not by game importance or spread size
- No head-to-head expert-vs-expert pairing (experts predict outcomes, they don't compete against each other)
- No real-time / in-season rating updates in v1 — ratings are computed as a batch after scoring
- No web UI — output is JSON, consumed by whatever displays the leaderboard

## Key Decisions

- **Baseline = Vegas favorite, not consensus**: Consensus pick would also work but Vegas favorite is a harder, more objective bar and doesn't depend on having enough experts per game to compute a meaningful consensus.
- **SU only**: ATS was initially preferred but all scraped picks are `pick_type: "straight_up"`. Retroactively checking whether SU picks covered the spread is not a meaningful skill signal.
- **Continuous time-based decay**: Each pick decays based on its actual game date, not season boundaries. Avoids artificial cliffs and naturally handles cross-season weighting without a separate mechanism.
- **Minimum pick count over per-season threshold**: A cumulative count (e.g., 100+) is more appropriate for cross-season ratings than requiring 50% of weeks in each individual season.
- **Letter grade + score**: Grades are intuitive (like 538 pollster ratings), scores provide granularity for close comparisons.
- **New standalone rating file**: Ratings go in a separate cross-season file, not embedded in existing per-season leaderboards.
- **Missing seasons are neutral**: With continuous decay, experts absent from a season naturally lose weight from old picks without being explicitly penalized.

## Dependencies / Assumptions

- **Results data**: Results files exist for all 5 seasons (2021-2025). Leaderboard scoring for 2021-2023 needs to be generated before ratings can be computed.
- **Spread data**: `spread_line` in results files is available for most games to determine the Vegas favorite. Games with missing spread data are excluded from baseline comparison but still counted for the expert's SU accuracy.
- **Expert identity**: Slug consistency across seasons and sources is assumed via `experts.json` and `slugify()`. Should be spot-checked during planning.
- **Historical pick integrity** (unverified): ESPN picks for 2021-2024 were scraped retroactively. CLAUDE.md warns the ESPN Core API overwrites picks with game winners. The HTML scraper may not have this issue, but historical pick accuracy should be validated before trusting ratings (e.g., spot-check games where experts picked underdogs — if no expert ever picked an underdog in historical data, the picks are likely corrupted).

## Outstanding Questions

### Deferred to Planning

- [Affects R1][Needs research] What specific formula should combine accuracy-over-baseline with consistency? Options include Bayesian rating, weighted average, or a composite score. The formula must ensure that sustained 68%+ across 3+ seasons outranks a single 75% season (Success Criteria #1).
- [Affects R3][Needs research] What continuous decay function and half-life produce good separation? (e.g., exponential decay with a half-life of N weeks). Should be tunable — try different half-lives and compare distributions.
- [Affects R5][Technical] What minimum pick count threshold produces a reasonable number of rated experts given the actual data? Analyze participation across 2021-2025 to find the right cutoff.
- [Affects R8][Technical] What score-to-grade thresholds produce a well-distributed grade curve? Should be calibrated against actual computed scores, not predetermined.
- [Affects R9][Technical] What should the rating output file structure look like? Standalone file at `data/scores/ratings.json` (or similar).
- [Affects R6][Technical] Validate historical ESPN pick integrity: spot-check 2021-2023 picks for evidence of underdog picks. If all historical picks match winners, the data is likely corrupted and those seasons should be excluded.

## Next Steps

→ `/ce:plan` for structured implementation planning
