---
title: "feat: Add ATS scoring using Vegas spread lines"
type: feat
status: completed
date: 2026-04-02
origin: docs/brainstorms/2026-04-02-vegas-spread-scoring-requirements.md
---

# feat: Add ATS scoring using Vegas spread lines

## Overview

Add against-the-spread (ATS) scoring to the expert picks tracker. The nflverse schedule data already includes `spread_line` for every game. This plan extends `fetch_results.py` to capture it and `score_experts.py` to compute ATS records alongside existing straight-up stats. No new dependencies or data sources.

## Problem Frame

Straight-up accuracy clusters around 60-70% because most experts pick favorites. ATS scoring reveals who makes sharp, value-aware picks by measuring whether the picked team covered the spread. (see origin: docs/brainstorms/2026-04-02-vegas-spread-scoring-requirements.md)

## Requirements Trace

- R1. Include `spread_line` in results JSON from nflverse schedule data
- R2. Exclude games with no spread data from ATS scoring
- R3. Score each straight-up pick ATS (did the picked team cover?)
- R4. ATS coverage: away covers when `away_score + spread_line > home_score`; home covers when `home_score > away_score + spread_line`
- R5. Pushes count as half-win (+0.5 correct, +1 total)
- R6. Add `ats_correct`, `ats_total`, `ats_accuracy` to leaderboard
- R7. Per-week ATS breakdowns in each expert's `weekly` array
- R8. Leaderboard sort order unchanged (straight-up accuracy)
- R9. Backfill existing results files; gracefully handle missing `spread_line`

## Scope Boundaries

- No new scrapers, dependencies, or data sources
- No separate ATS leaderboard — ATS columns augment the existing one
- No over/under or moneyline tracking
- No UI or visualization changes

## Context & Research

### Relevant Code and Patterns

- `scripts/fetch_results.py` — iterates `nfl.load_schedules()` rows at line 45, builds game dicts. Adding `spread_line` is one additional key in the dict literal (line 64-71).
- `scripts/score_experts.py` — `score_week()` (line 51-75) loops over picks, compares against winners. ATS logic parallels this loop. `build_leaderboard()` (line 78-123) aggregates weekly scores into cumulative totals — ATS fields follow the same pattern.
- `data/results/{season}/week-{N}.json` — current game schema: `game_id`, `away_team`, `home_team`, `away_score`, `home_score`, `winner`. Will gain `spread_line`.
- `data/scores/{season}/leaderboard.json` — current expert schema: `expert`, `expert_name`, `outlet`, `correct`, `total`, `accuracy`, `weekly[]`. Will gain `ats_correct`, `ats_total`, `ats_accuracy`, and per-week ATS fields.

### nflverse `spread_line` Convention

- Column is `Float64`, from the **away team's perspective** (positive = away is underdog)
- BAL @ KC with `spread_line=3.0` means KC favored by 3
- No null values found across 2024 or 2025 regular-season games (544 games checked)
- `0.0` (pick'em) is valid and degenerates to straight-up for ATS

## Key Technical Decisions

- **Store `spread_line` as-is** (away team perspective): Matches nflverse source data and the ATS formula in R4. No normalization needed. (see origin)
- **Push = half-win**: `ats_correct` is a `float`, not an `int`. Python `json.dumps` serializes `10.5` cleanly — 0.5 is exactly representable in IEEE 754.
- **Graceful degradation for old results files**: When a game dict lacks `spread_line`, skip ATS scoring for that game rather than crashing. This handles the migration window and satisfies R9.

## Open Questions

### Resolved During Planning

- **Store `spread_line` as-is or normalize?** — Store as-is. The ATS formula is written against the away-team convention. Normalization would add complexity with no benefit.
- **Float serialization risk?** — None. `0.5` is exact in IEEE 754. Accumulating half-wins stays clean.
- **Are there null `spread_line` values?** — No, verified across 544 regular-season games (2024-2025). The `spread_line is None` guard in R2 is a safety net, not an expected path.

### Deferred to Implementation

- Exact placement of ATS fields within the JSON output (before or after straight-up fields) — follow whatever reads naturally during implementation.

## Implementation Units

- [x] **Unit 1: Add `spread_line` to results JSON**

  **Goal:** Extend `fetch_results.py` to include the spread line in each game's result data.

  **Requirements:** R1, R2

  **Dependencies:** None

  **Files:**
  - Modify: `scripts/fetch_results.py`

  **Approach:**
  - In the `fetch_results()` function, read `row["spread_line"]` from the nflverse schedule row (already available from the `sched` DataFrame)
  - Add `"spread_line"` to the game dict built at lines 64-71
  - If `spread_line` is `None`, still include the key with a `null` value so the schema is consistent

  **Patterns to follow:**
  - The existing game dict construction at lines 64-71 — just add one more key

  **Test expectation:** None — this is a one-field addition to an existing dict literal with no branching logic. Verification is manual via the backfill step in Unit 3.

  **Verification:**
  - Running `uv run scripts/fetch_results.py --season 2024 --week 1` produces a results file where each game has a `spread_line` field

- [x] **Unit 2: Add ATS scoring to scorer and leaderboard**

  **Goal:** Extend `score_week()` to compute ATS results and `build_leaderboard()` to aggregate ATS stats.

  **Requirements:** R3, R4, R5, R6, R7, R8, R9

  **Dependencies:** Unit 1 (results files must have `spread_line`)

  **Files:**
  - Modify: `scripts/score_experts.py`

  **Approach:**

  `score_week()` changes:
  - Build a `spreads` dict alongside the existing `winners` dict: `{game_id: spread_line}`
  - For each pick, after the existing straight-up scoring, check ATS coverage if the game has a `spread_line` (graceful skip per R9)
  - Determine whether the picked team is the away or home team by comparing against `away_team`/`home_team` in results
  - Apply the coverage formula from R4; detect pushes (equality) per R5
  - Return both straight-up and ATS counts per expert: `{"correct": int, "total": int, "ats_correct": float, "ats_total": int}`

  `build_leaderboard()` changes:
  - Aggregate `ats_correct` and `ats_total` the same way `correct` and `total` are aggregated
  - Compute `ats_accuracy = round(ats_correct / ats_total, 3)` (0 when `ats_total` is 0)
  - Add `ats_correct`, `ats_total`, `ats_accuracy` to each expert dict
  - Add `ats_correct` and `ats_total` to the per-week breakdown in `weekly[]`
  - Sort order unchanged: `(-accuracy, -total)` per R8

  `score_week()` needs access to the full results dict (not just winners) to get `away_team`, `home_team`, and `spread_line`. Currently it receives the full results dict but only extracts `winner`. The additional fields are already available.

  **Patterns to follow:**
  - The existing `score_week()` loop structure: iterate picks, look up result by `game_id`, accumulate counts
  - The existing `build_leaderboard()` aggregation: sum per-week into cumulative, then sort

  **Test scenarios:**
  - Happy path: expert picks the away underdog (e.g., BAL +3 at KC), BAL loses 20-27 (margin 7 > spread 3) → ATS loss. Expert picks KC (home favorite), KC wins by 7 → ATS win.
  - Happy path: expert picks a team that wins straight-up but does NOT cover (e.g., favorite wins by less than the spread) → straight-up correct, ATS incorrect.
  - Happy path: expert picks a team that loses straight-up but DOES cover (underdog loses by less than spread) → straight-up incorrect, ATS correct.
  - Edge case: push — expert picks team, margin exactly equals spread → `ats_correct += 0.5`, `ats_total += 1`
  - Edge case: pick'em game (`spread_line = 0.0`) → ATS result equals straight-up result (no handicap)
  - Edge case: game result is a tie (`winner == "TIE"`) → skip both straight-up and ATS scoring (the existing `continue` on ties handles both; do not score ATS independently for ties)
  - Edge case: results file missing `spread_line` key on a game → straight-up scored normally, ATS skipped for that game
  - Integration: leaderboard `ats_accuracy` correctly reflects cumulative half-wins across weeks (e.g., 2 pushes over 10 games → `ats_correct=5.0`, `ats_total=10`, `ats_accuracy=0.5`)
  - Integration: leaderboard sort order remains by straight-up accuracy, not ATS accuracy

  **Verification:**
  - After backfill (Unit 3), `uv run scripts/score_experts.py --season 2024` produces a leaderboard where every expert has `ats_correct`, `ats_total`, and `ats_accuracy` fields
  - ATS accuracy values differ meaningfully from straight-up accuracy (confirming it's not just duplicating the same metric)
  - Existing straight-up fields (`correct`, `total`, `accuracy`) are identical to the pre-change leaderboard

- [x] **Unit 3: Backfill existing results files**

  **Goal:** Re-run `fetch_results.py` for all historical weeks so results files include `spread_line`.

  **Requirements:** R9

  **Dependencies:** Unit 1

  **Files:**
  - Modified by script re-run: `data/results/2024/week-{1..18}.json`, `data/results/2025/week-{1..18}.json`

  **Approach:**
  - Run `fetch_results.py` for each week of each season (2024 weeks 1-18, 2025 weeks 1-18)
  - This overwrites existing results files with the same data plus the new `spread_line` field
  - Safe because nflverse data for completed games is immutable

  **Test expectation:** None — this is a data migration step, not a code change.

  **Verification:**
  - Spot-check 2-3 results files to confirm `spread_line` is present on every game
  - Verify `spread_line` values against a known source (e.g., BAL @ KC Week 1 2024 should be `3.0`)

## System-Wide Impact

- **Unchanged invariants:** Straight-up scoring (`correct`, `total`, `accuracy`) is completely unaffected. The sort order, expert slugs, and weekly breakdown structure remain identical. Consumers of the leaderboard JSON that only read straight-up fields will see no change.
- **Schema addition:** Results JSON gains `spread_line` per game. Leaderboard JSON gains `ats_correct`, `ats_total`, `ats_accuracy` per expert and per week. These are additive — no existing fields are modified or removed.
- **Error propagation:** If `spread_line` is missing from a results game, ATS scoring silently skips that game. No new failure modes.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| nflverse removes or renames `spread_line` column | Low likelihood — it's a core column. If it happens, `fetch_results.py` will raise a `KeyError` immediately, which is the right failure mode. |
| Backfill overwrites manually edited results files | No manual edits exist — all results are machine-generated from nflverse. Safe to overwrite. |

## Sources & References

- **Origin document:** [docs/brainstorms/2026-04-02-vegas-spread-scoring-requirements.md](docs/brainstorms/2026-04-02-vegas-spread-scoring-requirements.md)
- Related code: `scripts/fetch_results.py`, `scripts/score_experts.py`
- nflverse schedule data: `spread_line` column verified via `nfl.load_schedules(2024)`
