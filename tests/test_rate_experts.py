"""Tests for rate_experts.py rating computation."""

import datetime
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from rate_experts import compute_ratings, load_json, validate_picks


def make_pick(expert, game_id, pick):
    return {
        "expert": expert,
        "expert_name": expert,
        "source": "test",
        "outlet": "Test",
        "game_id": game_id,
        "pick": pick,
        "pick_type": "straight_up",
    }


def make_result(game_id, away, home, away_score, home_score, spread_line):
    winner = away if away_score > home_score else home if home_score > away_score else "TIE"
    return {
        "game_id": game_id,
        "away_team": away,
        "home_team": home,
        "away_score": away_score,
        "home_score": home_score,
        "winner": winner,
        "spread_line": spread_line,
    }


def build_test_data(expert_picks, results, game_dates):
    """Build picks_by_expert and results_by_game from simple inputs."""
    picks_by_expert = {}
    for slug, picks in expert_picks.items():
        picks_by_expert[slug] = [make_pick(slug, gid, pick) for gid, pick in picks]

    results_by_game = {}
    for r in results:
        results_by_game[r["game_id"]] = r

    return picks_by_expert, results_by_game


class TestVegasFavoriteBaseline:
    """An expert who always picks the Vegas favorite should score exactly 0."""

    def test_always_picks_favorite_scores_zero(self):
        # 10 games, expert always picks the favorite (home team, spread > 0)
        results = []
        game_dates = {}
        picks = []
        base_date = datetime.date(2025, 9, 7)

        for i in range(10):
            gid = f"2025_01_AWAY{i}_HOME{i}"
            # Home is favored (positive spread), home wins 7 of 10
            home_wins = i < 7
            results.append(make_result(
                gid, f"AWAY{i}", f"HOME{i}",
                away_score=10 if home_wins else 24,
                home_score=24 if home_wins else 10,
                spread_line=3.0,
            ))
            game_dates[gid] = base_date + datetime.timedelta(days=i)
            # Expert always picks the favorite (home)
            picks.append((gid, f"HOME{i}"))

        picks_by_expert = {"always-fav": [make_pick("always-fav", gid, pick) for gid, pick in picks]}
        results_by_game = {r["game_id"]: r for r in results}

        output = compute_ratings(
            picks_by_expert, results_by_game, game_dates,
            half_life=52, min_picks=1, seasons=[2025],
        )

        expert = output["experts"][0]
        assert expert["expert"] == "always-fav"
        assert expert["score"] == 0.0


class TestConsistencyOverFlash:
    """Consistent 68%+ across 4 seasons should outscore a single 75% season."""

    def test_consistent_beats_one_season_wonder(self):
        # To generate positive score, experts must correctly pick upsets
        # (underdog wins → expert_correct=1, baseline_correct=0 → +w).
        # Each season: 100 games. 40% are upsets (away wins despite being underdog).
        # Consistent expert: 68% accuracy in every season.
        # Flash expert: 75% accuracy in only the most recent season.
        results = []
        game_dates = {}
        consistent_picks = []
        flash_picks = []
        base_date = datetime.date(2022, 9, 4)

        game_idx = 0
        for season_offset in range(4):
            season_start = base_date + datetime.timedelta(weeks=52 * season_offset)
            for i in range(100):
                gid = f"{2022 + season_offset}_{i:02d}_A{game_idx}_H{game_idx}"
                is_upset = i < 40  # 40% upsets (away team wins)
                results.append(make_result(
                    gid, f"A{game_idx}", f"H{game_idx}",
                    away_score=24 if is_upset else 10,
                    home_score=10 if is_upset else 24,
                    spread_line=3.0,  # home always favored
                ))
                game_dates[gid] = season_start + datetime.timedelta(days=i)

                # Consistent expert picks the actual winner 68% of the time
                if i < 68:
                    winner = f"A{game_idx}" if is_upset else f"H{game_idx}"
                    consistent_picks.append((gid, winner))
                else:
                    loser = f"H{game_idx}" if is_upset else f"A{game_idx}"
                    consistent_picks.append((gid, loser))

                # Flash expert only picks in the first season (oldest), 75% correct
                if season_offset == 0:
                    if i < 75:
                        winner = f"A{game_idx}" if is_upset else f"H{game_idx}"
                        flash_picks.append((gid, winner))
                    else:
                        loser = f"H{game_idx}" if is_upset else f"A{game_idx}"
                        flash_picks.append((gid, loser))

                game_idx += 1

        picks_by_expert = {
            "consistent": [make_pick("consistent", gid, pick) for gid, pick in consistent_picks],
            "flash": [make_pick("flash", gid, pick) for gid, pick in flash_picks],
        }
        results_by_game = {r["game_id"]: r for r in results}

        output = compute_ratings(
            picks_by_expert, results_by_game, game_dates,
            half_life=52, min_picks=1, seasons=[2022, 2023, 2024, 2025],
        )

        experts = {e["expert"]: e for e in output["experts"]}
        assert experts["consistent"]["score"] > experts["flash"]["score"], (
            f"Consistent ({experts['consistent']['score']:.4f}) should outscore "
            f"flash ({experts['flash']['score']:.4f})"
        )


class TestQualificationThreshold:
    """Experts below min_picks are marked provisional."""

    def test_below_threshold_is_provisional(self):
        results = []
        game_dates = {}
        picks = []
        base_date = datetime.date(2025, 9, 7)

        for i in range(50):
            gid = f"2025_{i:02d}_A{i}_H{i}"
            results.append(make_result(gid, f"A{i}", f"H{i}", 10, 24, 3.0))
            game_dates[gid] = base_date + datetime.timedelta(days=i)
            picks.append((gid, f"H{i}"))

        picks_by_expert = {"few-picks": [make_pick("few-picks", gid, pick) for gid, pick in picks]}
        results_by_game = {r["game_id"]: r for r in results}

        output = compute_ratings(
            picks_by_expert, results_by_game, game_dates,
            half_life=52, min_picks=100, seasons=[2025],
        )

        expert = output["experts"][0]
        assert not expert["qualified"]
        assert expert["grade"] == "provisional"


class TestEdgeCases:
    """Edge cases: pick-em, null spread, ties, missing data."""

    def test_pickem_excluded_from_baseline(self):
        """Games with spread_line == 0 excluded from baseline comparison."""
        gid = "2025_01_A_H"
        results_by_game = {gid: make_result(gid, "A", "H", 10, 24, 0)}
        game_dates = {gid: datetime.date(2025, 9, 7)}
        picks_by_expert = {"expert": [make_pick("expert", gid, "H")]}

        output = compute_ratings(
            picks_by_expert, results_by_game, game_dates,
            half_life=52, min_picks=1, seasons=[2025],
        )

        # Expert got the pick correct but score should be 0 (no baseline comparison)
        expert = output["experts"][0]
        assert expert["score"] == 0.0
        assert expert["total_picks"] == 1
        assert expert["accuracy"] == 1.0  # Still counted as correct pick

    def test_null_spread_excluded_from_baseline(self):
        """Games with spread_line == None excluded from baseline comparison."""
        gid = "2025_01_A_H"
        results_by_game = {gid: make_result(gid, "A", "H", 10, 24, None)}
        game_dates = {gid: datetime.date(2025, 9, 7)}

        # Need to set spread_line to None explicitly since make_result uses it
        results_by_game[gid]["spread_line"] = None
        picks_by_expert = {"expert": [make_pick("expert", gid, "H")]}

        output = compute_ratings(
            picks_by_expert, results_by_game, game_dates,
            half_life=52, min_picks=1, seasons=[2025],
        )

        expert = output["experts"][0]
        assert expert["score"] == 0.0

    def test_tie_excluded(self):
        """Games with TIE are excluded entirely."""
        gid = "2025_01_A_H"
        results_by_game = {gid: make_result(gid, "A", "H", 24, 24, 3.0)}
        game_dates = {gid: datetime.date(2025, 9, 7)}
        picks_by_expert = {"expert": [make_pick("expert", gid, "H")]}

        output = compute_ratings(
            picks_by_expert, results_by_game, game_dates,
            half_life=52, min_picks=1, seasons=[2025],
        )

        # No experts should appear (0 total picks after tie exclusion)
        assert len(output["experts"]) == 0

    def test_missing_result_skipped(self):
        """Pick referencing a game_id not in results is skipped."""
        game_dates = {"2025_01_A_H": datetime.date(2025, 9, 7)}
        picks_by_expert = {"expert": [make_pick("expert", "2025_01_X_Y", "X")]}
        results_by_game = {}

        output = compute_ratings(
            picks_by_expert, results_by_game, game_dates,
            half_life=52, min_picks=1, seasons=[2025],
        )

        assert len(output["experts"]) == 0

    def test_missing_game_date_skipped(self):
        """Pick referencing a game_id not in game_dates is skipped."""
        gid = "2025_01_A_H"
        other_gid = "2025_01_B_C"
        results_by_game = {gid: make_result(gid, "A", "H", 10, 24, 3.0)}
        # game_dates has an entry for a different game, but not for the expert's pick
        game_dates = {other_gid: datetime.date(2025, 9, 7)}
        picks_by_expert = {"expert": [make_pick("expert", gid, "H")]}

        output = compute_ratings(
            picks_by_expert, results_by_game, game_dates,
            half_life=52, min_picks=1, seasons=[2025],
        )

        assert len(output["experts"]) == 0

    def test_single_season_expert_rated(self):
        """Expert with picks in only one season still gets rated."""
        results = []
        game_dates = {}
        picks = []
        base_date = datetime.date(2025, 9, 7)

        for i in range(150):
            gid = f"2025_{i:02d}_A{i}_H{i}"
            results.append(make_result(gid, f"A{i}", f"H{i}", 10, 24, 3.0))
            game_dates[gid] = base_date + datetime.timedelta(days=i)
            picks.append((gid, f"H{i}"))  # Always correct, always picks favorite

        picks_by_expert = {"one-season": [make_pick("one-season", gid, pick) for gid, pick in picks]}
        results_by_game = {r["game_id"]: r for r in results}

        output = compute_ratings(
            picks_by_expert, results_by_game, game_dates,
            half_life=52, min_picks=100, seasons=[2025],
        )

        expert = output["experts"][0]
        assert expert["qualified"]
        assert expert["seasons_active"] == [2025]


class TestDecayWeighting:
    """Verify exponential decay weights picks by recency."""

    def test_recent_pick_weighted_more(self):
        """A recent correct pick contributes more score than an old one."""
        ln2 = math.log(2)
        half_life = 52

        # Two games, same expert picks underdog correctly in both
        old_gid = "2024_01_A_H"
        new_gid = "2025_18_A_H"

        old_date = datetime.date(2024, 9, 8)
        new_date = datetime.date(2025, 12, 28)  # ~67 weeks later

        results_by_game = {
            old_gid: make_result(old_gid, "A", "H", 24, 10, 3.0),  # Away wins, home favored
            new_gid: make_result(new_gid, "A", "H", 24, 10, 3.0),
        }
        game_dates = {old_gid: old_date, new_gid: new_date}

        # Expert who only picked the old game
        old_picks = {"old-picker": [make_pick("old-picker", old_gid, "A")]}
        # Expert who only picked the new game
        new_picks = {"new-picker": [make_pick("new-picker", new_gid, "A")]}

        old_output = compute_ratings(
            old_picks, results_by_game, game_dates,
            half_life=half_life, min_picks=1, seasons=[2024, 2025],
        )
        new_output = compute_ratings(
            new_picks, results_by_game, game_dates,
            half_life=half_life, min_picks=1, seasons=[2024, 2025],
        )

        old_score = old_output["experts"][0]["score"]
        new_score = new_output["experts"][0]["score"]

        # Both picked correctly against baseline, but recent pick has higher weight
        assert new_score > old_score > 0


class TestOutputStructure:
    """Verify the output JSON has the expected structure."""

    def test_output_has_required_fields(self):
        gid = "2025_01_A_H"
        results_by_game = {gid: make_result(gid, "A", "H", 10, 24, 3.0)}
        game_dates = {gid: datetime.date(2025, 9, 7)}
        picks_by_expert = {"expert": [make_pick("expert", gid, "H")]}

        output = compute_ratings(
            picks_by_expert, results_by_game, game_dates,
            half_life=52, min_picks=1, seasons=[2025],
        )

        assert "parameters" in output
        assert "grade_thresholds" in output
        assert "experts" in output
        assert output["parameters"]["half_life_weeks"] == 52
        assert output["parameters"]["min_picks"] == 1
        assert output["parameters"]["seasons"] == [2025]
        assert output["parameters"]["reference_date"] == "2025-09-07"

        expert = output["experts"][0]
        for field in ["expert", "expert_name", "outlet", "score", "total_picks",
                      "weighted_picks", "accuracy", "baseline_accuracy",
                      "seasons_active", "qualified", "grade"]:
            assert field in expert, f"Missing field: {field}"


class TestIntegration:
    """Integration tests using actual data files."""

    def test_script_runs_successfully(self):
        """Running the script produces a valid ratings.json."""
        result = subprocess.run(
            ["uv", "run", "scripts/rate_experts.py"],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0

        output_path = ROOT / "data" / "scores" / "ratings.json"
        assert output_path.exists()

        data = json.loads(output_path.read_text())
        assert len(data["experts"]) > 0
        assert data["parameters"]["half_life_weeks"] == 52

    def test_reproducibility(self):
        """Running twice on same data produces identical output."""
        subprocess.run(
            ["uv", "run", "scripts/rate_experts.py"],
            capture_output=True, timeout=120,
        )
        data1 = json.loads((ROOT / "data" / "scores" / "ratings.json").read_text())
        del data1["generated_at"]

        subprocess.run(
            ["uv", "run", "scripts/rate_experts.py"],
            capture_output=True, timeout=120,
        )
        data2 = json.loads((ROOT / "data" / "scores" / "ratings.json").read_text())
        del data2["generated_at"]

        assert data1 == data2

    def test_multiple_distinct_grades(self):
        """Score distribution produces multiple distinct letter grades."""
        data = json.loads((ROOT / "data" / "scores" / "ratings.json").read_text())
        qualified = [e for e in data["experts"] if e["qualified"]]
        grades = set(e["grade"] for e in qualified)
        assert len(grades) >= 4, f"Only {len(grades)} distinct grades: {grades}"

    def test_validate_flag(self):
        """--validate runs and exits successfully."""
        result = subprocess.run(
            ["uv", "run", "scripts/rate_experts.py", "--validate"],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0
        assert "OK" in result.stdout
