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
        "id",
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


def score_result(score: object) -> str:
    try:
        home, away = (int(value) for value in str(score).strip().split("-", maxsplit=1))
    except (TypeError, ValueError):
        return ""
    if home == away:
        return "D"
    return "H" if home > away else "A"


def prediction_result_code(prediction: object, score: object) -> str:
    prediction_text = str(prediction).strip()
    score_text = str(score).strip()
    if not prediction_text or prediction_text.lower() == "nan" or not score_result(score_text):
        return ""
    if prediction_text == score_text:
        return "W"
    return "D" if score_result(prediction_text) == score_result(score_text) else "L"


def apply_live_scores(
    predictions: pd.DataFrame,
    live_statuses: pd.DataFrame,
) -> pd.DataFrame:
    """Overlay provider scores and recalculate result codes for checked matches."""
    result = predictions.copy()
    if live_statuses.empty:
        return result

    for status in live_statuses.to_dict(orient="records"):
        home_score = status.get("Prediction Home Score", status.get("Home Score"))
        away_score = status.get("Prediction Away Score", status.get("Away Score"))
        if pd.isna(home_score) or pd.isna(away_score):
            continue
        match_id = str(status.get("matchlink", "")).strip()
        mask = result["id"].astype(str).str.strip().eq(match_id)
        if not mask.any():
            continue
        live_score = f"{int(home_score)}-{int(away_score)}"
        result.loc[mask, "Score"] = live_score
        for manager in PREDICTION_MANAGERS:
            result.loc[mask, RESULT_COLUMNS[manager]] = result.loc[
                mask, manager
            ].map(lambda prediction: prediction_result_code(prediction, live_score))
    return result


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
