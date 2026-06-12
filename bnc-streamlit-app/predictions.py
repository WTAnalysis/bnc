from __future__ import annotations

from pathlib import Path

import pandas as pd


PREDICTION_MANAGERS = [
    "Barlow",
    "Taylor",
    "Ian",
    "Will T",
    "Joe",
    "Dan",
    "Andy",
    "Will S",
]

RESULT_COLUMNS = {
    "Barlow": "SBR",
    "Taylor": "ATR",
    "Ian": "IUR",
    "Will T": "WTR",
    "Joe": "JSR",
    "Dan": "DWR",
    "Andy": "AMR",
    "Will S": "WSR",
}

RESULT_POINTS = {"W": 3, "D": 1, "L": 0}


def load_predictions(workbook_path: Path) -> pd.DataFrame:
    predictions = pd.read_excel(workbook_path, sheet_name="Predictor")
    required = [
        "description",
        "date",
        "time",
        "Round",
        "Score",
        *PREDICTION_MANAGERS,
        *RESULT_COLUMNS.values(),
    ]
    predictions = predictions[required].copy()
    predictions["date"] = pd.to_datetime(predictions["date"], errors="coerce")
    predictions["time"] = predictions["time"].astype(str).str.replace("Z", "", regex=False)
    return predictions


def prediction_league_table(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for manager in PREDICTION_MANAGERS:
        result_column = RESULT_COLUMNS[manager]
        codes = predictions[result_column].fillna("").astype(str).str.strip().str.upper()
        rows.append(
            {
                "Manager": manager,
                "Points": int(codes.map(RESULT_POINTS).fillna(0).sum()),
                "Correct Scores": int(codes.eq("W").sum()),
                "Correct Results": int(codes.eq("D").sum()),
            }
        )
    table = pd.DataFrame(rows).sort_values(
        ["Points", "Correct Scores", "Manager"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
    table.insert(0, "Rank", range(1, len(table) + 1))
    return table


def prediction_fixture_table(predictions: pd.DataFrame) -> pd.DataFrame:
    return predictions[
        [
            "description",
            "date",
            "time",
            "Round",
            "Score",
            *PREDICTION_MANAGERS,
        ]
    ].rename(
        columns={
            "description": "Fixture",
            "date": "Date",
            "time": "Time",
        }
    )
