---
date: 2026-04-02
topic: vegas-spread-scoring
---

# Vegas Spread Scoring for Expert Picks

## Problem Frame

The tracker currently evaluates experts on straight-up winner accuracy only. Straight-up records are a blunt instrument — most experts pick favorites, so accuracy clusters around 60-70% and doesn't reveal who makes sharp, value-aware predictions. Scoring existing straight-up picks against the Vegas spread (ATS) adds a more discriminating accuracy dimension without requiring new pick sources.

## Requirements

**Spread Data Capture**
- R1. Include the closing spread line for each game in the results JSON, sourced from nflverse schedule data (`spread_line` column).
- R2. Games with no spread data (e.g., pre-line or missing) are excluded from ATS scoring but still scored straight-up as today.

**ATS Scoring**
- R3. For each expert's straight-up pick, determine whether the picked team covered the spread.
- R4. ATS coverage logic: the away team covers when `away_score + spread_line > home_score`; the home team covers when `home_score > away_score + spread_line` (where `spread_line` is the away team's line per nflverse convention).
- R5. Pushes (pick lands exactly on the spread) count as a half-win: +0.5 to ATS correct, +1 to ATS total.

**Leaderboard**
- R6. Add ATS fields to the existing unified leaderboard: `ats_correct`, `ats_total`, `ats_accuracy` alongside current straight-up stats.
- R7. Include per-week ATS breakdowns in each expert's `weekly` array.
- R8. Leaderboard sort order remains by straight-up accuracy (existing behavior unchanged).

**Migration**
- R9. Existing results JSON files (which lack `spread_line`) must be backfilled by re-running `fetch_results.py` for all historical weeks. The scorer should also gracefully handle results files missing `spread_line` by skipping ATS scoring for those games.

## Success Criteria

- ATS records appear for all experts with picks for weeks that have spread data.
- Pushes are correctly scored as half-wins (verifiable against known games with pick-on-spread outcomes).
- Existing straight-up scoring is completely unaffected.

## Scope Boundaries

- No new pick scrapers or ATS-specific pick sources.
- No separate ATS leaderboard file — ATS columns are added to the existing leaderboard.
- No over/under or moneyline tracking (only spread).
- No UI or visualization changes.

## Key Decisions

- **Data source**: nflverse schedule data via `nflreadpy`, already loaded in `fetch_results.py`. No new dependency or API.
- **Push = half-win**: Standard sports-betting convention rather than excluding pushes (which is how ties are handled for straight-up).
- **Unified leaderboard**: ATS stats augment the existing leaderboard rather than creating a parallel one.
- **Store `spread_line` as-is**: Away team perspective, matching nflverse source data and the ATS formula in R4. No normalization needed.

## Next Steps

-> `/ce:plan` for structured implementation planning
