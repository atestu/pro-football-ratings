#!/usr/bin/env python3
"""
Compute cross-season expert ratings from raw picks and results.

Each expert receives a numerical score reflecting cumulative value over a
"pick the Vegas favorite" baseline, weighted by recency via exponential decay.
Scores map to letter grades (A+ through F).

Usage:
    python scripts/rate_experts.py                          # all seasons
    python scripts/rate_experts.py --seasons 2024 2025      # specific seasons
    python scripts/rate_experts.py --exclude-seasons 2021   # exclude corrupted
    python scripts/rate_experts.py --validate               # check pick integrity
    python scripts/rate_experts.py --half-life 78           # tune decay
"""

import argparse
import datetime
import json
import math
import sys
from pathlib import Path

import nflreadpy as nfl

ROOT = Path(__file__).resolve().parent.parent


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def discover_seasons() -> list[int]:
    """Find available seasons by scanning data/picks/ for season subdirectories."""
    picks_dir = ROOT / "data" / "picks"
    return sorted(
        int(d.name) for d in picks_dir.iterdir()
        if d.is_dir() and d.name.isdigit()
    )


def find_scored_weeks(season: int) -> list[int]:
    """Find weeks that have both picks and results files."""
    picks_dir = ROOT / "data" / "picks" / str(season)
    results_dir = ROOT / "data" / "results" / str(season)

    if not picks_dir.exists() or not results_dir.exists():
        return []

    picks_weeks = {
        int(f.stem.split("-")[1])
        for f in picks_dir.glob("week-*.json")
        if f.stem.split("-")[1].isdigit()
    }
    results_weeks = sorted(
        int(f.stem.split("-")[1])
        for f in results_dir.glob("week-*.json")
        if int(f.stem.split("-")[1]) in picks_weeks
    )
    return results_weeks


def load_game_dates(seasons: list[int]) -> dict[str, datetime.date]:
    """Load game dates from nflverse schedule. Returns {game_id: date}."""
    print(f"Loading nflverse schedules for {seasons}...")
    sched = nfl.load_schedules(seasons)
    game_dates = {}
    for row in sched.filter(sched["game_type"] == "REG").iter_rows(named=True):
        gameday = row["gameday"]
        if gameday is not None:
            if isinstance(gameday, str):
                game_dates[row["game_id"]] = datetime.date.fromisoformat(gameday)
            elif isinstance(gameday, datetime.date):
                game_dates[row["game_id"]] = gameday
    return game_dates


def load_all_picks_and_results(seasons: list[int]):
    """
    Load all picks and results across seasons, deduping by (expert, game_id).

    Returns:
        picks_by_expert: {slug: [{game_id, pick, ...}, ...]}
        results_by_game: {game_id: {winner, spread_line, away_team, home_team}}
    """
    picks_by_expert: dict[str, list[dict]] = {}
    results_by_game: dict[str, dict] = {}
    seen = set()

    for season in seasons:
        weeks = find_scored_weeks(season)
        if not weeks:
            print(f"  {season}: no scored weeks, skipping")
            continue

        # Load results for this season
        for w in weeks:
            results = load_json(ROOT / "data" / "results" / str(season) / f"week-{w}.json")
            if not results:
                continue
            for g in results["games"]:
                results_by_game[g["game_id"]] = g

        # Load picks for this season (ESPN first, then FN, NFL, PFT — dedup)
        for w in weeks:
            picks_dir = ROOT / "data" / "picks" / str(season)
            sources = [
                load_json(picks_dir / f"week-{w}.json"),
                load_json(picks_dir / f"week-{w}-fantasynerds.json"),
                load_json(picks_dir / f"week-{w}-nfl.json"),
                load_json(picks_dir / f"week-{w}-pft.json"),
            ]
            for source in sources:
                if not source:
                    continue
                for p in source["picks"]:
                    key = (p["expert"], p["game_id"])
                    if key not in seen:
                        seen.add(key)
                        slug = p["expert"]
                        if slug not in picks_by_expert:
                            picks_by_expert[slug] = []
                        picks_by_expert[slug].append(p)

        print(f"  {season}: {len(weeks)} weeks loaded")

    return picks_by_expert, results_by_game


def validate_picks(seasons: list[int]) -> None:
    """Check per-season wrong-pick rates for ESPN picks to detect data corruption."""
    print("Validating historical pick integrity...\n")

    header = f"{'Season':>6}  {'Total':>6}  {'Wrong':>6}  {'Wrong%':>7}  {'Status'}"
    print(header)
    print("-" * len(header))

    all_healthy = True
    for season in seasons:
        picks_dir = ROOT / "data" / "picks" / str(season)
        results_dir = ROOT / "data" / "results" / str(season)

        if not picks_dir.exists() or not results_dir.exists():
            print(f"{season:>6}  {'—':>6}  {'—':>6}  {'—':>7}  No data")
            continue

        # Load results for this season
        results_by_game = {}
        for f in results_dir.glob("week-*.json"):
            data = load_json(f)
            if data:
                for g in data["games"]:
                    results_by_game[g["game_id"]] = g

        # Load ESPN picks only (week-N.json, not week-N-*.json)
        total = 0
        wrong = 0
        for f in sorted(picks_dir.glob("week-*.json")):
            # Skip non-ESPN files (fantasynerds, nfl, pft)
            if "-" in f.stem.split("week-", 1)[1]:
                continue
            data = load_json(f)
            if not data:
                continue
            for p in data["picks"]:
                game = results_by_game.get(p["game_id"])
                if not game or game["winner"] == "TIE":
                    continue
                total += 1
                if p["pick"] != game["winner"]:
                    wrong += 1

        if total == 0:
            print(f"{season:>6}  {'—':>6}  {'—':>6}  {'—':>7}  No ESPN picks")
            continue

        rate = wrong / total
        status = "OK" if rate >= 0.10 else "SUSPECT — wrong-pick rate too low"
        if rate < 0.10:
            all_healthy = False
        print(f"{season:>6}  {total:>6}  {wrong:>6}  {rate:>7.1%}  {status}")

    print()
    if all_healthy:
        print("All seasons show healthy wrong-pick rates. Data is usable.")
    else:
        print("WARNING: Some seasons have suspiciously low wrong-pick rates.")
        print("Consider using --exclude-seasons to exclude corrupted seasons.")


def compute_ratings(
    picks_by_expert: dict[str, list[dict]],
    results_by_game: dict[str, dict],
    game_dates: dict[str, datetime.date],
    half_life: float,
    min_picks: int,
    seasons: list[int],
) -> dict:
    """Compute cross-season expert ratings."""
    # Reference date = most recent game date in the dataset
    all_dates = [d for d in game_dates.values()]
    if not all_dates:
        print("No game dates found. Cannot compute ratings.")
        sys.exit(1)
    reference_date = max(all_dates)
    ln2 = math.log(2)

    # Load expert registry for display names
    registry_path = ROOT / "data" / "experts.json"
    registry = json.loads(registry_path.read_text()) if registry_path.exists() else {"experts": []}
    expert_info = {e["expert"]: e for e in registry["experts"]}

    expert_stats: dict[str, dict] = {}

    for slug, picks in picks_by_expert.items():
        stats = {
            "score": 0.0,
            "total_picks": 0,
            "weighted_picks": 0.0,
            "correct": 0,
            "baseline_correct": 0,
            "baseline_total": 0,
            "seasons_active": set(),
        }

        for p in picks:
            game_id = p["game_id"]
            game = results_by_game.get(game_id)
            if not game:
                continue
            if game["winner"] == "TIE":
                continue

            game_date = game_dates.get(game_id)
            if not game_date:
                continue

            # Parse season from game_id (e.g., "2024_01_BAL_KC")
            game_season = int(game_id.split("_")[0])
            stats["seasons_active"].add(game_season)
            stats["total_picks"] += 1

            expert_correct = 1 if p["pick"] == game["winner"] else 0
            stats["correct"] += expert_correct

            # Compute decay weight
            age_weeks = (reference_date - game_date).days / 7
            w = math.exp(-ln2 * age_weeks / half_life)
            stats["weighted_picks"] += w

            # Baseline: Vegas favorite
            spread_line = game.get("spread_line")
            if spread_line is None or spread_line == 0:
                # No baseline comparison for pick-em or missing spread
                # Still count the pick for total_picks but no score contribution
                # from baseline comparison
                continue

            stats["baseline_total"] += 1

            # Determine Vegas favorite: positive spread = home favored,
            # negative spread = away favored
            if spread_line > 0:
                vegas_fav = game["home_team"]
            else:
                vegas_fav = game["away_team"]

            baseline_correct = 1 if vegas_fav == game["winner"] else 0
            stats["baseline_correct"] += baseline_correct

            # Score contribution: w × (expert_correct − baseline_correct)
            stats["score"] += w * (expert_correct - baseline_correct)

        if stats["total_picks"] > 0:
            stats["seasons_active"] = sorted(stats["seasons_active"])
            expert_stats[slug] = stats

    # Build expert records
    experts = []
    for slug, stats in expert_stats.items():
        info = expert_info.get(slug, {})
        accuracy = round(stats["correct"] / stats["total_picks"], 4) if stats["total_picks"] else 0
        baseline_acc = round(stats["baseline_correct"] / stats["baseline_total"], 4) if stats["baseline_total"] else 0
        qualified = stats["total_picks"] >= min_picks

        experts.append({
            "expert": slug,
            "expert_name": info.get("expert_name", slug),
            "outlet": info.get("outlet", "Unknown"),
            "score": round(stats["score"], 4),
            "total_picks": stats["total_picks"],
            "weighted_picks": round(stats["weighted_picks"], 4),
            "accuracy": accuracy,
            "baseline_accuracy": baseline_acc,
            "seasons_active": stats["seasons_active"],
            "qualified": qualified,
            "grade": None,  # filled in below
        })

    # Sort qualified experts by score descending
    qualified_experts = [e for e in experts if e["qualified"]]
    unqualified_experts = [e for e in experts if not e["qualified"]]

    if not qualified_experts:
        print("No qualified experts found. Try lowering --min-picks.")
        # Still produce output with all provisional
        for e in experts:
            e["grade"] = "provisional"
        return _build_output(experts, {}, half_life, min_picks, seasons, reference_date)

    qualified_experts.sort(key=lambda e: -e["score"])

    # Auto-calibrate grade thresholds using percentile-based distribution.
    # Score = 0 anchors at C (baseline performance).
    # Experts with score >= 0 are distributed across C through A+ by percentile.
    # Experts with score < 0 are distributed across D+ through F by percentile.
    positive = sorted([e["score"] for e in qualified_experts if e["score"] >= 0])
    negative = sorted([e["score"] for e in qualified_experts if e["score"] < 0])

    positive_grades = ["C", "C+", "B-", "B", "B+", "A-", "A", "A+"]  # low to high
    negative_grades = ["F", "D-", "D", "D+"]  # low to high

    thresholds = {"C": 0.0}

    def percentile_thresholds(scores: list[float], grades: list[str]) -> dict[str, float]:
        """Set thresholds so experts distribute roughly evenly across grades."""
        if not scores or len(grades) < 2:
            return {}
        result = {}
        n = len(scores)
        for i, grade in enumerate(grades):
            idx = int(i * n / len(grades))
            result[grade] = scores[idx]
        return result

    if len(positive) > 1:
        thresholds.update(percentile_thresholds(positive, positive_grades))
    elif len(positive) == 1:
        # Single positive expert gets C
        pass

    if len(negative) > 1:
        thresholds.update(percentile_thresholds(negative, negative_grades))
    elif len(negative) == 1:
        thresholds["D+"] = negative[0]

    # Grade assignment: walk from highest grade down, first match wins
    grade_order = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "D+", "D", "D-", "F"]

    def score_to_grade(score: float) -> str:
        for grade in grade_order:
            if grade in thresholds and score >= thresholds[grade]:
                return grade
        return "F"

    # Assign grades
    for e in qualified_experts:
        e["grade"] = score_to_grade(e["score"])
    for e in unqualified_experts:
        e["grade"] = "provisional"

    all_experts = qualified_experts + sorted(unqualified_experts, key=lambda e: -e["score"])

    return _build_output(all_experts, thresholds, half_life, min_picks, seasons, reference_date)


def _build_output(
    experts: list[dict],
    grade_thresholds: dict,
    half_life: float,
    min_picks: int,
    seasons: list[int],
    reference_date: datetime.date,
) -> dict:
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "parameters": {
            "half_life_weeks": half_life,
            "min_picks": min_picks,
            "seasons": seasons,
            "reference_date": reference_date.isoformat(),
        },
        "grade_thresholds": grade_thresholds,
        "experts": experts,
    }


def print_summary(output: dict) -> None:
    """Print a summary of the rating results."""
    experts = output["experts"]
    qualified = [e for e in experts if e["qualified"]]
    provisional = [e for e in experts if not e["qualified"]]

    print(f"\n{'=' * 60}")
    print(f"  Cross-Season Expert Ratings")
    print(f"  Seasons: {output['parameters']['seasons']}")
    print(f"  Half-life: {output['parameters']['half_life_weeks']} weeks")
    print(f"  Min picks: {output['parameters']['min_picks']}")
    print(f"  Reference date: {output['parameters']['reference_date']}")
    print(f"{'=' * 60}")
    print(f"\n  {len(qualified)} qualified experts, {len(provisional)} provisional\n")

    # Grade distribution
    grades: dict[str, int] = {}
    for e in qualified:
        grades[e["grade"]] = grades.get(e["grade"], 0) + 1
    print("  Grade distribution:")
    for grade in ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "D+", "D", "D-", "F"]:
        if grade in grades:
            print(f"    {grade:<3} {grades[grade]}")

    # Top 25
    # Measure max name/outlet widths for alignment
    top = qualified[:25]
    name_w = max((len(e["expert_name"]) for e in top), default=6)
    outlet_w = max((len(e["outlet"]) for e in top), default=6)
    print(f"\n  {'#':>3}  {'Grade':<5}  {'Expert':<{name_w}}  {'Outlet':<{outlet_w}}  {'Score':>8}  {'Acc':>6}  {'Picks':>5}")
    print(f"  {'-' * (22 + name_w + outlet_w + 22)}")
    for i, e in enumerate(top, 1):
        print(f"  {i:>3}  {e['grade']:<5}  {e['expert_name']:<{name_w}}  {e['outlet']:<{outlet_w}}  {e['score']:>8.2f}  {e['accuracy']:>5.1%}  {e['total_picks']:>5}")
    print()


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute cross-season expert ratings"
    )
    parser.add_argument(
        "--seasons", type=int, nargs="+", default=None,
        help="Seasons to include (default: all available)",
    )
    parser.add_argument(
        "--exclude-seasons", type=int, nargs="+", default=None,
        help="Seasons to exclude from rating",
    )
    parser.add_argument(
        "--half-life", type=float, default=52,
        help="Decay half-life in weeks (default: 52)",
    )
    parser.add_argument(
        "--min-picks", type=int, default=100,
        help="Minimum picks for qualification (default: 100)",
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="Validate historical pick integrity and exit",
    )
    return parser.parse_args()


def main():
    args = get_args()

    # Determine seasons
    if args.seasons:
        seasons = sorted(args.seasons)
    else:
        seasons = discover_seasons()

    if args.exclude_seasons:
        seasons = [s for s in seasons if s not in args.exclude_seasons]

    if not seasons:
        print("No seasons to process.")
        sys.exit(0)

    # Validation mode
    if args.validate:
        validate_picks(seasons)
        sys.exit(0)

    print(f"Computing ratings for seasons: {seasons}")
    print(f"  Half-life: {args.half_life} weeks, Min picks: {args.min_picks}\n")

    # Load data
    game_dates = load_game_dates(seasons)
    picks_by_expert, results_by_game = load_all_picks_and_results(seasons)

    print(f"\n  {len(picks_by_expert)} experts, {len(results_by_game)} games loaded")

    # Compute ratings
    output = compute_ratings(
        picks_by_expert, results_by_game, game_dates,
        half_life=args.half_life,
        min_picks=args.min_picks,
        seasons=seasons,
    )

    # Write output
    scores_dir = ROOT / "data" / "scores"
    scores_dir.mkdir(parents=True, exist_ok=True)
    output_path = scores_dir / "ratings.json"
    output_path.write_text(json.dumps(output, indent=2) + "\n")
    print(f"Wrote ratings for {len(output['experts'])} experts to {output_path}")

    print_summary(output)


if __name__ == "__main__":
    main()
