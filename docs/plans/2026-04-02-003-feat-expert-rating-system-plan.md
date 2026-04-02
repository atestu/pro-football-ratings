---
title: "feat: Add cross-season expert rating system"
type: feat
status: completed
date: 2026-04-02
origin: docs/brainstorms/2026-04-02-expert-elo-rating-requirements.md
deepened: 2026-04-02
---

# feat: Add cross-season expert rating system

## Overview

Add a `rate_experts.py` script that computes cross-season ratings for NFL pick experts. Each expert receives a numerical score reflecting cumulative value over a "pick the Vegas favorite" baseline, weighted by recency via exponential decay. Scores map to letter grades (A+ through F). Output is a standalone `data/scores/ratings.json` file, separate from existing per-season leaderboards.

## Problem Frame

The current leaderboard resets every season — a consistently strong expert over 4 seasons looks identical to a one-season wonder. There is no durable measure of expert quality that accounts for longevity, consistency, or whether an expert actually adds value beyond naive strategies. (see origin: docs/brainstorms/2026-04-02-expert-elo-rating-requirements.md)

## Requirements Trace

- R1. Numerical rating blending accuracy-over-baseline and consistency (solved via cumulative weighted sum — see Key Technical Decisions)
- R2. Vegas favorite baseline from `spread_line` in results files (positive = home favored, negative = away favored); pick-em games (`spread_line == 0`) and games with missing spread data (`spread_line == null`) excluded from baseline comparison
- R3. Continuous time-based decay using game dates from nflverse schedule; no season boundary effects
- R4. Straight-up picks only — no ATS component
- R5. Minimum pick count threshold (placeholder 100+) for qualification; unqualified experts marked provisional
- R6. All available seasons (2021-2025) used, pending historical data integrity validation
- R7. Missing seasons are neutral — decay handles absence naturally
- R8. Letter grades A+ through F from numerical score thresholds
- R9. Standalone cross-season output at `data/scores/ratings.json`

## Scope Boundaries

- No ATS component (picks are straight-up only)
- No upset bonus or variable game weighting — picks weighted only by recency
- No head-to-head expert pairing
- No real-time / in-season updates — batch computation only
- No web UI — JSON output only
- No modification to existing per-season leaderboards
- Leaderboard generation for 2021-2023 is useful independently but NOT a prerequisite for ratings (the rating script reads raw picks + results directly)

## Context & Research

### Relevant Code and Patterns

- `scripts/score_experts.py` — template for script structure: `ROOT`, `load_json()`, `argparse`, `find_scored_weeks()`, JSON I/O with `indent=2` + trailing newline, `(expert, game_id)` dedup pattern
- `scripts/normalize.py` — `normalize_team()`, `slugify()` utilities
- `data/experts.json` — 110 unique expert slugs, canonical identity store
- `data/picks/{season}/week-{N}*.json` — pick records with `expert`, `game_id`, `pick`, `pick_type`
- `data/results/{season}/week-{N}.json` — game results with `winner`, `spread_line`, `away_team`, `home_team`
- `nflreadpy.load_schedules()` — returns Polars DataFrame with `game_id` and `gameday` columns for game dates
- `.github/workflows/score-experts.yml` — triggered on push to `data/results/**`, template for CI integration

### Key Data Facts

- **`spread_line` present everywhere**: Confirmed no null or zero values across all 90 results files (2021-2025). The pick-em exclusion (R2) is defensive but unlikely to trigger on current data.
- **`kickoff` only in ESPN picks**: Game dates for decay must come from nflverse schedule, not from pick files.
- **Source coverage varies by season**: ESPN for all 5 seasons (2021-2025, full coverage); Fantasy Nerds for 2021-2023 (full), 2024 (sparse — only 4 of 18 weeks have picks), 2025 (full); PFT for 2025 only (2024 PFT file exists but contains zero picks); NFL.com for 2025 only. NFL.com experts (~5) will have ~250 picks; PFT experts (~2) borderline on 100-pick threshold.
- **Historical data risk**: CLAUDE.md warns the ESPN Core API overwrites picks with winners after results. The HTML scraper may not have this issue, but 2021-2023 ESPN picks should be validated.

## Key Technical Decisions

- **Cumulative weighted sum, not weighted average**: `score = Σ(w_i × (expert_correct_i − baseline_correct_i))` where `w_i = exp(−ln(2) × age_weeks / half_life)`. A sum (not average) naturally rewards both skill AND longevity — more games with positive margin accumulates more total value. This satisfies the key success criterion: consistent 68% over 3+ seasons outscores a single 75% season without needing a separate "consistency signal." Rationale: a weighted average would favor the one-season wonder with higher accuracy; a cumulative sum rewards the expert who showed up and performed across years. **Note on value asymmetry:** picking with the baseline (same as Vegas favorite) always contributes 0 regardless of outcome. Picking against the baseline is a higher-variance bet: +w_i when the underdog wins (expert right, baseline wrong), -w_i when the favorite wins (expert wrong, baseline right). This means contrarian experts are rewarded or penalized more per pick than consensus followers — intentional, as this measures value *over* the baseline strategy.

- **Exponential decay with configurable half-life**: Starting at 52 weeks (1 year), exposed as `--half-life` flag. At 52 weeks: 1yr-old picks carry 50% weight, 2yr-old carry 25%, 4yr-old carry 6.25%. This keeps ~4 seasons of meaningful data while strongly favoring recent performance.

- **Baseline = Vegas favorite per game, not a fixed percentage**: For each game, determine the Vegas favorite from `spread_line` sign. The baseline "expert" picks that team. This makes the baseline game-aware — in an easy week the baseline does well, in a chaotic week it doesn't. An expert who matches the baseline every game scores exactly 0 → C grade.

- **Read raw picks + results directly**: The rating script reads pick files and results files from all seasons, rather than consuming per-season leaderboard JSONs. This is necessary because: (a) per-game granularity is needed for date-based decay weighting, (b) per-game baseline comparison requires `spread_line` from results, (c) leaderboards for 2021-2023 don't exist yet. Reuses the `(expert, game_id)` dedup pattern from `score_experts.py` (lines 257-266): load ESPN first, then Fantasy Nerds, NFL.com, PFT per week; skip any `(expert, game_id)` pair already seen. This dedup is load-bearing — without it, ESPN experts who also appear in Fantasy Nerds files would be double-counted.

- **Grade thresholds calibrated post-computation**: Score = 0 anchors at C (baseline performance). Other thresholds are set after examining the actual score distribution rather than predetermined. The thresholds are stored in the output file for transparency and reproducibility.

- **nflverse schedule as sole source for game dates**: `nfl.load_schedules(seasons)` provides `gameday` per `game_id`. Loaded once per run, joined to picks by `game_id`. The `kickoff` field in ESPN pick files is NOT used — it only exists in ESPN picks (not Fantasy Nerds, PFT, or NFL.com), so relying on it would create source-dependent behavior. Always use nflverse schedule for consistency across all pick sources.

- **Source-coverage asymmetry is a known limitation**: ESPN experts have picks across all 5 seasons (2021-2025) while Fantasy Nerds coverage is patchy in 2021-2023, and NFL.com/PFT sources only exist for 2024-2025. The cumulative sum formula structurally favors experts from better-scraped sources (more observed games = more signal). This is accepted for v1 — ratings reflect the data available, and experts with more observed picks have more evidence supporting their rating. A future enhancement could normalize contributions per-week rather than per-game if this becomes a concern.

## Open Questions

### Resolved During Planning

- **What formula combines accuracy and consistency?** Cumulative weighted value-over-baseline (sum). The cumulative nature inherently rewards consistency — see Key Technical Decisions.
- **What decay function?** Exponential decay with half-life parameter, defaulting to 52 weeks.
- **Should the script consume leaderboard JSONs or raw data?** Raw picks + results — per-game granularity is required for decay and baseline comparison.
- **Does `spread_line` exist in 2021-2023 results?** Yes — confirmed present in all 90 results files across all seasons.

### Deferred to Implementation

- **Exact half-life value**: Starting at 52 weeks but should be tuned by comparing score distributions at 52, 78, and 104 weeks.
- **Exact minimum pick count**: Starting at 100 but should be verified against actual expert participation data — how many experts qualify at various thresholds?
- **Exact grade thresholds**: Depend on the actual score distribution. Implementation should compute scores first, then set thresholds to produce a well-spread grade curve.
- **Historical pick corruption severity**: Unit 1 validates this. If 2021-2023 ESPN picks are corrupted, those seasons are excluded from ratings (Fantasy Nerds picks for the same period may still be valid).

## Implementation Units

- [ ] **Unit 1: Validate historical ESPN pick integrity (quick sanity check)**

**Goal:** Confirm that 2021-2023 ESPN picks are not corrupted by the API overwrite issue. Preliminary analysis during planning already shows healthy wrong-pick rates (~38% for 2021-2023, consistent with 2024-2025 control data), so this is a lightweight confirmation step, not a full investigation.

**Requirements:** R6 (all available seasons used, pending validation)

**Dependencies:** None

**Files:**
- Read: `data/picks/2021/week-*.json`, `data/picks/2022/week-*.json`, `data/picks/2023/week-*.json` (ESPN format only, not `*-fantasynerds.json`)
- Read: `data/results/2021/week-*.json`, `data/results/2022/week-*.json`, `data/results/2023/week-*.json`

**Approach:**
- Implement as an inline `--validate` flag on `rate_experts.py` (not a separate script) — when passed, print the validation summary and exit
- For each season 2021-2025, load ESPN pick files and corresponding results
- Count wrong picks (expert picked the losing team), compute wrong-pick rate per season
- In healthy data, experts should pick wrong ~30-40% of the time. If a season's wrong-pick rate is < 10%, that season's data is likely corrupted
- Print a summary table: season, total picks, wrong picks, wrong-pick rate
- If any season fails validation, print a warning and recommend using `--exclude-seasons` when running ratings. The `--exclude-seasons` flag on `rate_experts.py` is the handoff mechanism: Unit 1 identifies bad seasons, the user passes them via `--exclude-seasons` to Unit 2

**Patterns to follow:**
- Inline validation flag pattern (e.g., `--validate` prints diagnostics and exits)

**Test scenarios:**
- Happy path: Run `--validate`, output per-season wrong-pick rates. All seasons show ~30-40% wrong picks (confirmed during planning: 2021=37.9%, 2022=37.9%, 2023=39.0%)
- Edge case: A season where results files exist but no ESPN pick files → skip gracefully with a message

**Verification:**
- `--validate` output shows per-season wrong-pick rates
- All 5 seasons show healthy rates (~30-40%), confirming data is usable

- [ ] **Unit 2: Core rating script (`scripts/rate_experts.py`)**

**Goal:** Compute cross-season expert ratings from raw picks and results, output `data/scores/ratings.json`.

**Requirements:** R1, R2, R3, R4, R5, R7, R8, R9

**Dependencies:** Unit 1 (determines which seasons to include)

**Files:**
- Create: `scripts/rate_experts.py`
- Read: `data/picks/{season}/week-{N}*.json` (all four source file patterns per week)
- Read: `data/results/{season}/week-{N}.json`
- Read: `data/experts.json`
- Create: `data/scores/ratings.json`
- Test: `tests/test_rate_experts.py` (greenfield — no `tests/` directory or pytest config exists yet; this unit creates both, and adds `pytest>=7.0` to `requirements.txt`)

**Approach:**
- Follow `score_experts.py` conventions: shebang, docstring, `ROOT`, `load_json()`, `argparse`. Note: the standard `--season`/`--week` pattern does not directly apply since ratings are cross-season by nature. Instead: `--seasons` (optional, defaults to all available by scanning `data/picks/` for season subdirectories), `--exclude-seasons` (optional, for excluding seasons with corrupted data — see Unit 1), `--half-life` (default 52), `--min-picks` (default 100, but implementer should run an exploratory pass: compute expert pick counts and check how many qualify at 50/100/150/200 thresholds before finalizing the default). Discover available seasons via `[int(d.name) for d in (ROOT / "data" / "picks").iterdir() if d.is_dir()]` — this is a new pattern not present in existing single-season scripts
- Load nflverse schedule via `nfl.load_schedules(seasons)` for game dates. The `gameday` column contains ISO date strings (`"YYYY-MM-DD"`) that need parsing via `datetime.date.fromisoformat()` before date arithmetic. Build a `game_id → date` lookup dict from the Polars DataFrame
- For each season/week, load all four pick source files (ESPN, Fantasy Nerds, NFL.com, PFT) and dedup by `(expert, game_id)` with ESPN priority — same pattern as `score_experts.py`
- For each pick, look up the game result and game date. Skip games where `winner == "TIE"` (per existing convention), `spread_line == 0` (pick-em, R2), or `spread_line is null` (missing spread data)
- Determine the Vegas favorite: if `spread_line > 0` → home team; if `spread_line < 0` → away team
- Compute `reference_date = max(gameday)` across all game records loaded from the nflverse schedule for the selected seasons. This is the most recent game date in the dataset — NOT today's date — ensuring reproducibility regardless of when the script runs. Then compute `age_weeks = (reference_date − gameday).days / 7` for each pick
- Compute `w_i = exp(−ln(2) × age_weeks / half_life)` for each pick
- Per expert: accumulate `Σ(w_i × (expert_correct − baseline_correct))` as the score, plus `total_picks`, `weighted_picks = Σw_i`, and per-season participation
- Apply minimum pick count threshold (R5): experts below threshold get `qualified: false`, grade `"provisional"`
- Sort qualified experts by score descending. Map scores to letter grades using auto-calibrated thresholds: the script computes all scores first, then sets grade boundaries algorithmically. Score = 0 anchors at C (baseline). Positive scores distribute across C+/B-/B/B+/A-/A/A+ using the score range (e.g., evenly spaced or percentile-based). Negative scores distribute across D+/D/D-/F. The implementer should try both approaches (even spacing vs percentile) and pick whichever produces better spread across grades. Thresholds are stored in `ratings.json` for reproducibility — this is NOT a manual calibration step
- Write `data/scores/ratings.json` with: generation metadata, parameters (half_life, min_picks, seasons, reference_date), per-expert records (slug, name, outlet, grade, score, total_picks, weighted_picks, accuracy, baseline_accuracy, seasons_active, qualified), and grade_thresholds used
- Print a summary: total experts rated, grade distribution, top 10 by score

**Patterns to follow:**
- `score_experts.py` for overall script structure, `load_json()`, `find_scored_weeks()` discovery, JSON output formatting
- `score_experts.py` lines 257-266 for `(expert, game_id)` dedup across sources
- `fetch_results.py` for nflverse schedule loading pattern

**Test scenarios:**
- Happy path: Given a known set of picks and results across multiple seasons, verify the computed score matches the expected cumulative weighted value over baseline
- Happy path: An expert who always picks the Vegas favorite scores exactly 0
- Happy path: An expert with 68% accuracy across 4 seasons scores higher than one with 75% in 1 season (the key success criterion — construct test data to verify)
- Edge case: Expert with fewer picks than `min_picks` is marked provisional and ungraded
- Edge case: Game with `spread_line == 0` (pick-em) is excluded from both score and baseline comparison
- Edge case: Game with `spread_line == null` (missing spread) is excluded from baseline comparison
- Edge case: Game with `winner == "TIE"` is excluded entirely
- Edge case: Expert with picks in only one season still gets rated (if above min_picks threshold)
- Error path: Pick references a `game_id` not found in results → skip with warning, do not crash
- Error path: Pick references a `game_id` not found in nflverse schedule (no date) → skip with warning
- Integration: Running the script twice on identical data produces identical `ratings.json` output (reproducibility)
- Integration: Score distribution produces multiple distinct letter grades (not all clustered in one bucket)

**Verification:**
- `data/scores/ratings.json` is produced with valid structure
- Experts are sorted by score descending within qualified experts
- Score of 0 maps to C grade
- No expert who always picks favorites scores significantly above or below 0
- Running twice produces identical output

- [ ] **Unit 3: CI workflow integration**

**Goal:** Run `rate_experts.py` automatically after scoring updates, committing `data/scores/ratings.json`.

**Requirements:** R9 (rating output is produced and maintained)

**Dependencies:** Unit 2

**Files:**
- Modify: `.github/workflows/score-experts.yml` (add rating step after scoring)
- Modify: `.github/workflows/fetch-results.yml` (add rating step after scoring, if scoring also runs here)

**Approach:**
- Add a rating step after `score_experts.py` in the CI workflows. The natural home is `score-experts.yml` (triggered on push to `data/results/**`), since ratings should regenerate whenever scoring data changes. Also add to `fetch-results.yml` if it runs scoring inline.
- The step runs `python scripts/rate_experts.py` unconditionally (ratings depend on all seasons, not just the current one)
- **Must use `continue-on-error: true`** on the rating step so that a failure (e.g., nflverse timeout) does not block the leaderboard commit. This matches the stated design intent: "CI should not gate other commits on rating success."
- The existing `git add data/scores/` step in the workflows already covers `data/scores/ratings.json` — no staging change needed
- No new workflow file needed — piggyback on the existing scoring triggers

**Patterns to follow:**
- Existing workflow steps in `score-experts.yml` and `fetch-results.yml` for step syntax, commit patterns, and `pip install -r requirements.txt` (not uv) for CI

**Test scenarios:**
- Test expectation: none — CI configuration, verified by workflow run

**Verification:**
- After a scoring update, `ratings.json` is regenerated and committed
- The workflow does not fail if `ratings.json` already exists (overwrite is fine)

## System-Wide Impact

- **Interaction graph:** The rating script is a pure consumer of existing data files (picks, results, experts.json) and producer of a new file (ratings.json). It does not modify any existing files or interact with scrapers/scorers at runtime.
- **Error propagation:** If the rating script fails, it does not affect existing scoring or scraping. CI should not gate other commits on rating success.
- **State lifecycle risks:** `ratings.json` is regenerated from scratch each run — no incremental state to corrupt. The `reference_date` parameter ensures reproducibility regardless of when the script runs.
- **API surface parity:** No other interfaces consume `ratings.json` yet. The output structure should be designed for future consumption (web UI, etc.) but no parity concerns today.
- **Integration coverage:** The rating script depends on pick file format, results file format, and nflverse schedule schema. Changes to any of these (e.g., new pick sources, results field changes) could affect ratings.
- **Unchanged invariants:** Existing per-season `leaderboard.json` files, pick files, results files, and `experts.json` are not modified. The scoring pipeline continues to work independently.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| 2021-2023 ESPN picks are corrupted (API overwrite issue) | Unit 1 validates before ratings are computed. If corrupted, exclude those seasons (Fantasy Nerds picks from the same period may still be usable). Ratings degrade gracefully with fewer seasons — the formula still works. |
| Half-life or grade thresholds produce poor differentiation | Parameters are exposed as CLI flags for tuning. Implementation defers calibration to actual score distributions rather than hardcoding. |
| nflverse schedule data has gaps for older seasons | Unlikely (nflverse covers all NFL seasons), but picks without matching schedule dates are skipped with a warning rather than crashing. |
| Expert slugs are inconsistent across seasons | Spot-checked during research: `experts.json` has 110 unique slugs with no collisions. Fantasy Nerds experts like `pete-prisco` and `matt-bowen` appear consistently across 2021-2025. |
| Minimum pick threshold excludes too many / too few experts | Start at 100, tune based on actual participation data. The threshold is a CLI parameter. |
| Source-coverage asymmetry inflates ESPN-sourced experts' scores | Accepted for v1 — cumulative sum reflects observed evidence, and more data = more signal is defensible. Document as a known limitation. Future enhancement could normalize per-week instead of per-game. |

## Sources & References

- **Origin document:** [docs/brainstorms/2026-04-02-expert-elo-rating-requirements.md](docs/brainstorms/2026-04-02-expert-elo-rating-requirements.md)
- Related code: `scripts/score_experts.py` (scoring pipeline template), `scripts/normalize.py` (shared utilities)
- Data: `data/picks/`, `data/results/`, `data/experts.json`, `data/scores/`
- CI: `.github/workflows/fetch-results.yml`, `.github/workflows/score-experts.yml`
