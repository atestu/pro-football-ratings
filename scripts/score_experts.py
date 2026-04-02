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
        if f.stem.split("-")[1].isdigit()
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
    Returns {expert_slug: {"correct": int, "total": int,
                           "ats_correct": float, "ats_total": int}}.
    """
    games = {g["game_id"]: g for g in results["games"]}

    scores: dict[str, dict] = {}
    for pick in picks["picks"]:
        game = games.get(pick["game_id"])
        if not game:
            print(f"  Warning: no result for game {pick['game_id']}")
            continue
        if game["winner"] == "TIE":
            continue

        slug = pick["expert"]
        if slug not in scores:
            scores[slug] = {"correct": 0, "total": 0, "ats_correct": 0.0, "ats_total": 0}

        scores[slug]["total"] += 1
        if pick["pick"] == game["winner"]:
            scores[slug]["correct"] += 1

        # ATS scoring — skip if spread data is missing (R2, R9)
        spread_line = game.get("spread_line")
        if spread_line is None:
            continue

        scores[slug]["ats_total"] += 1
        picked = pick["pick"]
        adjusted_away = game["away_score"] + spread_line

        if picked == game["away_team"]:
            # Away team covers when away_score + spread_line > home_score
            if adjusted_away > game["home_score"]:
                scores[slug]["ats_correct"] += 1
            elif adjusted_away == game["home_score"]:
                scores[slug]["ats_correct"] += 0.5  # push
        else:
            # Home team covers when home_score > away_score + spread_line
            if game["home_score"] > adjusted_away:
                scores[slug]["ats_correct"] += 1
            elif game["home_score"] == adjusted_away:
                scores[slug]["ats_correct"] += 0.5  # push

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
                cumulative[slug] = {
                    "correct": 0, "total": 0,
                    "ats_correct": 0.0, "ats_total": 0,
                    "weekly": [],
                }
            entry = cumulative[slug]
            entry["correct"] += data["correct"]
            entry["total"] += data["total"]
            entry["ats_correct"] += data.get("ats_correct", 0.0)
            entry["ats_total"] += data.get("ats_total", 0)
            entry["weekly"].append({
                "week": week,
                "correct": data["correct"],
                "total": data["total"],
                "ats_correct": data.get("ats_correct", 0.0),
                "ats_total": data.get("ats_total", 0),
            })

    # Build sorted list
    total_scored_weeks = len(weekly_scores)
    experts = []
    for slug, data in cumulative.items():
        info = expert_info.get(slug, {})
        accuracy = round(data["correct"] / data["total"], 3) if data["total"] else 0
        ats_accuracy = round(data["ats_correct"] / data["ats_total"], 3) if data["ats_total"] else 0
        weeks_participated = len(data["weekly"])
        experts.append({
            "expert": slug,
            "expert_name": info.get("expert_name", slug),
            "outlet": info.get("outlet", "Unknown"),
            "correct": data["correct"],
            "total": data["total"],
            "accuracy": accuracy,
            "ats_correct": data["ats_correct"],
            "ats_total": data["ats_total"],
            "ats_accuracy": ats_accuracy,
            "qualified": weeks_participated / total_scored_weeks >= 0.5 if total_scored_weeks else True,
            "weekly": data["weekly"],
        })

    experts.sort(key=lambda e: (-e["accuracy"], -e["total"]))

    return {
        "season": season,
        "through_week": max(weekly_scores.keys()),
        "experts": experts,
    }


def print_leaderboard(leaderboard: dict, sort_by: str = "pct", outlet: str | None = None) -> None:
    """Print leaderboard as a formatted table."""
    experts = leaderboard["experts"]

    if outlet:
        outlet_lower = outlet.lower()
        experts = [e for e in experts if outlet_lower in e["outlet"].lower()]

    if sort_by == "ats":
        experts.sort(key=lambda e: (-e["ats_accuracy"], -e["ats_total"]))

    if not experts:
        print("No experts to display.")
        return

    title = f"  {leaderboard['season']} NFL Expert Picks — Through Week {leaderboard['through_week']}"
    if outlet:
        title += f" ({outlet})"
    sort_label = "ATS%" if sort_by == "ats" else "Pct"
    title += f"  [sorted by {sort_label}]"

    # Pre-format all rows so we can measure actual widths
    rows = []
    for i, e in enumerate(experts, 1):
        wl = f"{e['correct']}-{e['total'] - e['correct']}"
        pct = f"{e['accuracy']:.1%}"
        ats_w = e["ats_correct"]
        ats_l = e["ats_total"] - e["ats_correct"]
        ats = f"{ats_w:g}-{ats_l:g}"
        ats_pct = f"{e['ats_accuracy']:.1%}" if e["ats_total"] else "—"
        rows.append((str(i), e["expert_name"], e["outlet"], wl, pct, ats, ats_pct))

    headers = ("#", "Expert", "Outlet", "W-L", "Pct", "ATS", "ATS%")
    # Column alignment: left for name/outlet, right for everything else
    aligns = ("r", "l", "l", "r", "r", "r", "r")

    widths = [max(len(h), max((len(r[c]) for r in rows), default=0))
              for c, h in enumerate(headers)]

    def fmt_row(cells):
        parts = []
        for val, w, a in zip(cells, widths, aligns):
            parts.append(f"{val:>{w}}" if a == "r" else f"{val:<{w}}")
        return "  ".join(parts)

    header_line = fmt_row(headers)
    rule_width = len(header_line)

    print(f"\n{'=' * rule_width}")
    print(title)
    print(f"{'=' * rule_width}")
    print(header_line)
    print(f"{'-' * rule_width}")
    for row in rows:
        print(fmt_row(row))
    print()


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score expert picks")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=None)
    parser.add_argument("--table", action="store_true", help="Print leaderboard as a table")
    parser.add_argument("--sort", choices=["pct", "ats"], default="pct", help="Sort by: pct (straight-up) or ats (against the spread)")
    parser.add_argument("--outlet", type=str, default=None, help="Filter by outlet (substring match, e.g. 'ESPN', 'CBS')")
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
        picks_dir = ROOT / "data" / "picks" / str(season)
        espn_picks = load_json(picks_dir / f"week-{w}.json")
        fn_picks = load_json(picks_dir / f"week-{w}-fantasynerds.json")
        nfl_picks = load_json(picks_dir / f"week-{w}-nfl.json")
        pft_picks = load_json(picks_dir / f"week-{w}-pft.json")
        results = load_json(ROOT / "data" / "results" / str(season) / f"week-{w}.json")

        all_picks_list = []
        seen = set()
        for source in (espn_picks, fn_picks, nfl_picks, pft_picks):
            if not source:
                continue
            for p in source["picks"]:
                key = (p["expert"], p["game_id"])
                if key not in seen:
                    seen.add(key)
                    all_picks_list.append(p)

        if not all_picks_list:
            print(f"  No picks files for Week {w}, skipping")
            continue
        if not results:
            print(f"  No results file for Week {w}, skipping")
            continue

        sources = []
        if espn_picks:
            sources.append(f"ESPN:{len(espn_picks['picks'])}")
        if fn_picks:
            sources.append(f"FN:{len(fn_picks['picks'])}")
        if nfl_picks:
            sources.append(f"NFL:{len(nfl_picks['picks'])}")
        if pft_picks:
            sources.append(f"PFT:{len(pft_picks['picks'])}")

        combined = {"picks": all_picks_list}
        print(f"  Week {w}: {len(all_picks_list)} picks ({', '.join(sources)}), {len(results['games'])} games")
        weekly_scores[w] = score_week(combined, results)

    if not weekly_scores:
        print("No weeks could be scored.")
        sys.exit(0)

    leaderboard = build_leaderboard(season, weekly_scores)

    scores_dir = ROOT / "data" / "scores" / str(season)
    scores_dir.mkdir(parents=True, exist_ok=True)
    scores_path = scores_dir / "leaderboard.json"
    scores_path.write_text(json.dumps(leaderboard, indent=2) + "\n")
    print(f"Wrote leaderboard with {len(leaderboard['experts'])} experts to {scores_path}")

    if args.table:
        print_leaderboard(leaderboard, sort_by=args.sort, outlet=args.outlet)


if __name__ == "__main__":
    main()
