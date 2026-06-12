from datetime import datetime, timezone
from pathlib import Path

from config import POINTS_DIR, WORKBOOK_PATH
from league_data import build_league_data, due_missing_matches


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
