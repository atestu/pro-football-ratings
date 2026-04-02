#!/usr/bin/env python3
"""
Score expert picks against game results and build/update the leaderboard.

Reads picks and results JSON files, grades each expert, and produces
a cumulative leaderboard sorted by accuracy.

Usage:
    python scripts/score_experts.py [--season 2024] [--week 1]

If --week is omitted, scores all weeks that have both picks and results.
"""

import argparse
import json
import sys
from pathlib import Path

import nflreadpy as nfl

ROOT = Path(__file__).resolve().parent.parent


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def find_scored_weeks(season: int) -> list[int]:
    """Find weeks that have both picks and results files."""
    picks_dir = ROOT / "data" / "picks" / str(season)
    results_dir = ROOT / "data" / "results" / str(season)

    if not picks_dir.exists() or not results_dir.exists():
        return []

    picks_weeks = {
        int(f.stem.split("-")[1])
        for f in picks_dir.glob("week-*.json")
    }
    results_weeks = sorted(
        int(f.stem.split("-")[1])
        for f in results_dir.glob("week-*.json")
        if int(f.stem.split("-")[1]) in picks_weeks
    )
    return results_weeks


def score_week(picks: dict, results: dict) -> dict[str, dict]:
    """
    Score one week's picks against results.
    Returns {expert_slug: {"correct": int, "total": int}}.
    """
    winners = {g["game_id"]: g["winner"] for g in results["games"]}

    scores: dict[str, dict] = {}
    for pick in picks["picks"]:
        winner = winners.get(pick["game_id"])
        if not winner:
            print(f"  Warning: no result for game {pick['game_id']}")
            continue
        if winner == "TIE":
            continue

        slug = pick["expert"]
        if slug not in scores:
            scores[slug] = {"correct": 0, "total": 0}

        scores[slug]["total"] += 1
        if pick["pick"] == winner:
            scores[slug]["correct"] += 1

    return scores


def build_leaderboard(
    season: int, weekly_scores: dict[int, dict[str, dict]]
) -> dict:
    """Build cumulative leaderboard from weekly scores."""
    # Load expert registry for display names
    registry_path = ROOT / "data" / "experts.json"
    registry = json.loads(registry_path.read_text()) if registry_path.exists() else {"experts": []}
    expert_info = {e["expert"]: e for e in registry["experts"]}

    # Aggregate
    cumulative: dict[str, dict] = {}
    for week, scores in sorted(weekly_scores.items()):
        for slug, data in scores.items():
            if slug not in cumulative:
                cumulative[slug] = {"correct": 0, "total": 0, "weekly": []}
            entry = cumulative[slug]
            entry["correct"] += data["correct"]
            entry["total"] += data["total"]
            entry["weekly"].append({
                "week": week,
                "correct": data["correct"],
                "total": data["total"],
            })

    # Build sorted list
    experts = []
    for slug, data in cumulative.items():
        info = expert_info.get(slug, {})
        accuracy = round(data["correct"] / data["total"], 3) if data["total"] else 0
        experts.append({
            "expert": slug,
            "expert_name": info.get("expert_name", slug),
            "outlet": info.get("outlet", "Unknown"),
            "correct": data["correct"],
            "total": data["total"],
            "accuracy": accuracy,
            "weekly": data["weekly"],
        })

    experts.sort(key=lambda e: (-e["accuracy"], -e["total"]))

    return {
        "season": season,
        "through_week": max(weekly_scores.keys()),
        "experts": experts,
    }


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score expert picks")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=None)
    return parser.parse_args()


def main():
    args = get_args()

    season = args.season or nfl.get_current_season()

    if args.week:
        weeks_to_score = [args.week]
        print(f"Scoring {season} Week {args.week}...")
    else:
        weeks_to_score = find_scored_weeks(season)
        print(f"Scoring {season} — found {len(weeks_to_score)} weeks with picks and results")

    if not weeks_to_score:
        print("No weeks to score.")
        sys.exit(0)

    weekly_scores: dict[int, dict[str, dict]] = {}
    for w in weeks_to_score:
        picks = load_json(ROOT / "data" / "picks" / str(season) / f"week-{w}.json")
        results = load_json(ROOT / "data" / "results" / str(season) / f"week-{w}.json")

        if not picks:
            print(f"  No picks file for Week {w}, skipping")
            continue
        if not results:
            print(f"  No results file for Week {w}, skipping")
            continue

        print(f"  Week {w}: {len(picks['picks'])} picks, {len(results['games'])} games")
        weekly_scores[w] = score_week(picks, results)

    if not weekly_scores:
        print("No weeks could be scored.")
        sys.exit(0)

    leaderboard = build_leaderboard(season, weekly_scores)

    scores_dir = ROOT / "data" / "scores" / str(season)
    scores_dir.mkdir(parents=True, exist_ok=True)
    scores_path = scores_dir / "leaderboard.json"
    scores_path.write_text(json.dumps(leaderboard, indent=2) + "\n")
    print(f"Wrote leaderboard with {len(leaderboard['experts'])} experts to {scores_path}")


if __name__ == "__main__":
    main()
