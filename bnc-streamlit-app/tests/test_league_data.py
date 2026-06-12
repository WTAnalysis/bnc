from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config import POINTS_DIR, WORKBOOK_PATH
from league_data import build_league_data, due_missing_matches, ordered_lineup
from live_scores import candidate_matches, format_england_time
from predictions import (
    apply_live_scores,
    load_predictions,
    prediction_league_table,
)


def test_builds_all_managers_and_stages():
    data = build_league_data(WORKBOOK_PATH, POINTS_DIR)
    assert len(data.league_table) == 8
    assert data.selections["Manager"].nunique() == 8
    assert data.selections["Stage"].nunique() == 8
    assert len(data.selections) == 8 * 16 * 8


def test_captain_is_only_bonus_multiplier():
    data = build_league_data(WORKBOOK_PATH, POINTS_DIR)
    multipliers = data.selections.groupby("Selection")["Multiplier"].first().to_dict()
    assert multipliers["Captain"] == 2.0
    assert multipliers["Vice Captain"] == 1.0
    assert multipliers["Picked"] == 1.0
    assert multipliers["Sub 1"] == 0.0


def test_existing_matches_are_not_due():
    data = build_league_data(WORKBOOK_PATH, POINTS_DIR)
    due = due_missing_matches(
        data.schedule,
        POINTS_DIR,
        now=datetime(2026, 6, 12, 16, 0, tzinfo=timezone.utc),
    )
    existing = {
        path.name.removesuffix("_playerlog.xlsx")
        for path in Path(POINTS_DIR).glob("*_playerlog.xlsx")
    }
    assert existing.isdisjoint(set(due["matchlink"]))


def test_lineup_order_is_starters_then_bench():
    data = build_league_data(WORKBOOK_PATH, POINTS_DIR)
    lineup = data.lineup_scores[
        (data.lineup_scores["Manager"] == "Ian")
        & (data.lineup_scores["Stage"] == "G1")
    ]
    ordered = ordered_lineup(lineup)
    active = ordered.iloc[:11]
    assert set(active["Selection"]) <= {"Picked", "Captain", "Vice Captain"}
    assert active["Position"].map({"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}).is_monotonic_increasing
    assert ordered["Selection"].iloc[11:].tolist() == [
        "Sub GK",
        "Sub 1",
        "Sub 2",
        "Sub 3",
        "Sub 4",
    ]


def test_schedule_is_displayed_in_england_time():
    data = build_league_data(WORKBOOK_PATH, POINTS_DIR)
    fixture = data.schedule[
        data.schedule["matchlink"] == "y1ow9ht5baxn64i01hq9moes"
    ].iloc[0]
    assert fixture["kickoff"].strftime("%H:%M %Z") == "19:00 UTC"
    assert fixture["kickoff_uk"].strftime("%H:%M %Z") == "20:00 BST"


def test_live_candidates_include_nearby_fixture():
    data = build_league_data(WORKBOOK_PATH, POINTS_DIR)
    nearby = candidate_matches(
        data.schedule,
        now=datetime(2026, 6, 12, 18, 24, tzinfo=timezone.utc),
    )
    assert "y1ow9ht5baxn64i01hq9moes" in set(nearby["matchlink"])
    assert format_england_time("2026-06-12T18:40:00Z").endswith("19:40:00 BST")


def test_prediction_league_table_uses_result_codes():
    predictions = load_predictions(WORKBOOK_PATH)
    table = prediction_league_table(predictions).set_index("Manager")
    assert table.loc["Barlow", "Points"] == 4
    assert table.loc["Ian", "Points"] == 4
    assert table.loc["Taylor", "Points"] == 2
    assert table.loc["Will S", "Points"] == 1


def test_live_score_updates_prediction_score_and_points():
    predictions = load_predictions(WORKBOOK_PATH)
    live_statuses = pd.DataFrame(
        [
            {
                "matchlink": "y1ow9ht5baxn64i01hq9moes",
                "Home Score": 0,
                "Away Score": 1,
            }
        ]
    )
    updated = apply_live_scores(predictions, live_statuses)
    fixture = updated[
        updated["id"].astype(str).str.strip() == "y1ow9ht5baxn64i01hq9moes"
    ].iloc[0]
    assert fixture["Score"] == "0-1"
    assert fixture["ATR"] == "W"
    assert fixture["WSR"] == "L"
    original_table = prediction_league_table(predictions).set_index("Manager")
    updated_table = prediction_league_table(updated).set_index("Manager")
    assert updated_table.loc["Taylor", "Points"] == original_table.loc["Taylor", "Points"] + 3
    assert updated_table.loc["Will S", "Points"] == original_table.loc["Will S", "Points"]
