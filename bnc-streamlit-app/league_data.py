from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from config import (
    MANAGER_SHEETS,
    MATCH_COMPLETION_BUFFER_HOURS,
    SELECTION_MULTIPLIERS,
    STAGES,
)


@dataclass
class LeagueData:
    schedule: pd.DataFrame
    picked_players: pd.DataFrame
    selections: pd.DataFrame
    player_match_points: pd.DataFrame
    player_stage_points: pd.DataFrame
    lineup_scores: pd.DataFrame
    stage_totals: pd.DataFrame
    draft_round_scores: pd.DataFrame
    league_table: pd.DataFrame


def normalize_manager(value: object) -> str:
    return str(value).strip().replace("WillT", "Will T").replace("WillS", "Will S")


def ordered_lineup(lineup: pd.DataFrame) -> pd.DataFrame:
    selection_order = {
        "Picked": 0,
        "Captain": 0,
        "Vice Captain": 0,
        "Sub GK": 1,
        "Sub 1": 2,
        "Sub 2": 3,
        "Sub 3": 4,
        "Sub 4": 5,
    }
    position_order = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
    result = lineup.copy()
    result["_selection_order"] = result["Selection"].map(selection_order).fillna(6)
    result["_position_order"] = result["Position"].map(position_order).fillna(4)
    return (
        result.sort_values(
            ["_selection_order", "_position_order", "Player"],
            ascending=[True, True, True],
        )
        .drop(columns=["_selection_order", "_position_order"])
        .reset_index(drop=True)
    )


def load_schedule(workbook_path: Path) -> pd.DataFrame:
    schedule = pd.read_excel(workbook_path, sheet_name="schedule")
    schedule.columns = [str(column).strip() for column in schedule.columns]
    schedule["matchlink"] = schedule["matchlink"].astype(str).str.strip()
    schedule["Round"] = schedule["Round"].astype(str).str.strip()
    date_part = schedule["date"].dt.strftime("%Y-%m-%d")
    time_part = schedule["time"].astype(str).str.replace("Z", "", regex=False)
    schedule["kickoff"] = pd.to_datetime(
        date_part + " " + time_part,
        utc=True,
        errors="coerce",
    )
    schedule["kickoff_uk"] = schedule["kickoff"].dt.tz_convert("Europe/London")
    return schedule[schedule["Round"].isin(STAGES)].copy()


def load_picked_players(workbook_path: Path) -> pd.DataFrame:
    players = pd.read_excel(workbook_path, sheet_name="PickedPlayers")
    players["Manager"] = players["Manager"].map(normalize_manager)
    players["Player"] = players["Player"].astype(str).str.strip()
    players["player_id"] = players["player_id"].astype(str).str.strip()
    return players


def load_selections(workbook_path: Path, players: pd.DataFrame) -> pd.DataFrame:
    lookup = players.set_index(["Manager", "Player"])["player_id"].to_dict()
    nation_lookup = players.set_index(["Manager", "Player"])["Nation"].to_dict()
    rows: list[dict] = []

    for manager, sheet_name in MANAGER_SHEETS.items():
        sheet = pd.read_excel(workbook_path, sheet_name=sheet_name, header=None)
        for row_number in range(2, len(sheet)):
            player = str(sheet.iat[row_number, 1]).strip()
            if not player or player == "nan":
                continue
            for stage_index, stage in enumerate(STAGES):
                selection_column = 4 + (stage_index * 3)
                selection = sheet.iat[row_number, selection_column]
                selection = "" if pd.isna(selection) else str(selection).strip()
                rows.append(
                    {
                        "Manager": manager,
                        "Stage": stage,
                        "Position": sheet.iat[row_number, 0],
                        "Player": player,
                        "Country": nation_lookup.get((manager, player), ""),
                        "player_id": lookup.get((manager, player), ""),
                        "Selection": selection,
                        "Multiplier": SELECTION_MULTIPLIERS.get(selection, 0.0),
                    }
                )
    return pd.DataFrame(rows)


def load_point_files(points_dir: Path, schedule: pd.DataFrame) -> pd.DataFrame:
    frames = []
    round_lookup = schedule.set_index("matchlink")["Round"].to_dict()

    for path in sorted(points_dir.glob("*_playerlog.xlsx")):
        match_id = path.name.removesuffix("_playerlog.xlsx").strip()
        frame = pd.read_excel(path)
        if "player_id" not in frame or "Total Score" not in frame:
            continue
        frame["match_id"] = match_id
        frame["Stage"] = round_lookup.get(match_id)
        frame["player_id"] = frame["player_id"].astype(str).str.strip()
        frames.append(frame)

    if not frames:
        return pd.DataFrame(
            columns=["match_id", "Stage", "player_id", "player_name", "team_name", "Total Score"]
        )
    return pd.concat(frames, ignore_index=True)


def build_draft_round_scores(
    players: pd.DataFrame,
    stage_points: pd.DataFrame,
) -> pd.DataFrame:
    base_columns = [
        "Round",
        "Pick",
        "Manager",
        "Player",
        "Nation",
        "Position",
        "player_id",
    ]
    draft = players[base_columns].copy()
    draft = draft[
        draft["Manager"].astype(str).str.strip().str.lower().ne("nan")
        & draft["Player"].astype(str).str.strip().str.lower().ne("nan")
        & draft["player_id"].astype(str).str.strip().str.lower().ne("nan")
        & draft["player_id"].astype(str).str.strip().ne("")
    ].copy()
    draft["Round"] = pd.to_numeric(draft["Round"], errors="coerce").astype("Int64")
    draft["Pick"] = pd.to_numeric(draft["Pick"], errors="coerce").astype("Int64")

    stage_pivot = (
        stage_points.pivot_table(
            index="player_id",
            columns="Stage",
            values="Player Points",
            aggfunc="sum",
        )
        .reindex(columns=STAGES)
        .fillna(0.0)
    )
    draft = draft.merge(stage_pivot, on="player_id", how="left")
    for stage in STAGES:
        draft[stage] = draft[stage].fillna(0.0)

    draft["Total"] = draft[STAGES].sum(axis=1)
    draft = draft.sort_values(
        ["Round", "Total", "Pick", "Player"],
        ascending=[True, False, False, True],
    ).reset_index(drop=True)
    draft["Draft Rank"] = draft.groupby("Round").cumcount() + 1
    draft["Bonus"] = draft["Draft Rank"].eq(1).astype(int) * 3
    return draft


def build_league_data(workbook_path: Path, points_dir: Path) -> LeagueData:
    schedule = load_schedule(workbook_path)
    players = load_picked_players(workbook_path)
    selections = load_selections(workbook_path, players)
    match_points = load_point_files(points_dir, schedule)

    stage_points = (
        match_points.dropna(subset=["Stage"])
        .groupby(["Stage", "player_id"], as_index=False)["Total Score"]
        .sum()
        .rename(columns={"Total Score": "Player Points"})
    )
    lineup = selections.merge(stage_points, on=["Stage", "player_id"], how="left")
    lineup["Player Points"] = lineup["Player Points"].fillna(0.0)
    lineup["Lineup Points"] = lineup["Player Points"] * lineup["Multiplier"]

    totals = (
        lineup.groupby(["Manager", "Stage"], as_index=False)["Lineup Points"]
        .sum()
        .rename(columns={"Lineup Points": "Points"})
    )
    totals["Stage"] = pd.Categorical(totals["Stage"], categories=STAGES, ordered=True)
    totals = totals.sort_values(["Stage", "Points", "Manager"], ascending=[True, False, True])

    draft_round_scores = build_draft_round_scores(players, stage_points)
    draft_bonus = (
        draft_round_scores[draft_round_scores["Draft Rank"] == 1]
        .groupby("Manager", as_index=False)["Bonus"]
        .sum()
    )

    fantasy_totals = (
        totals.groupby("Manager", as_index=False)["Points"]
        .sum()
    )
    league = fantasy_totals.merge(draft_bonus, on="Manager", how="left")
    league["Bonus"] = league["Bonus"].fillna(0).astype(int)
    league["Total"] = league["Points"] + league["Bonus"]
    league = league.sort_values(
        ["Total", "Points", "Manager"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
    league.insert(0, "Rank", range(1, len(league) + 1))

    return LeagueData(
        schedule=schedule,
        picked_players=players,
        selections=selections,
        player_match_points=match_points,
        player_stage_points=stage_points,
        lineup_scores=lineup,
        stage_totals=totals,
        draft_round_scores=draft_round_scores,
        league_table=league,
    )


def point_file_ids(points_dir: Path) -> set[str]:
    return {
        path.name.removesuffix("_playerlog.xlsx").strip()
        for path in points_dir.glob("*_playerlog.xlsx")
    }


def recent_fixtures(
    fixtures: pd.DataFrame,
    now: datetime | None = None,
    hours: float = 48,
) -> pd.DataFrame:
    """Return fixtures that have kicked off within the requested recent window."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    return fixtures[
        fixtures["kickoff"].notna()
        & fixtures["kickoff"].between(cutoff, now)
    ].copy()


def due_missing_matches(
    schedule: pd.DataFrame,
    points_dir: Path,
    now: datetime | None = None,
) -> pd.DataFrame:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=MATCH_COMPLETION_BUFFER_HOURS)
    existing = point_file_ids(points_dir)
    due = schedule[
        schedule["kickoff"].notna()
        & (schedule["kickoff"] <= cutoff)
        & ~schedule["matchlink"].isin(existing)
    ].copy()
    return due.sort_values("kickoff")


def fixture_status(schedule: pd.DataFrame, points_dir: Path) -> pd.DataFrame:
    status = schedule.copy()
    existing = point_file_ids(points_dir)
    now = datetime.now(timezone.utc)
    status["Data"] = status["matchlink"].map(
        lambda match_id: "Ready" if match_id in existing else "Missing"
    )
    status["Fixture"] = status["description"].fillna(
        status["Home_Team"].fillna("TBC") + " vs " + status["Away_Team"].fillna("TBC")
    )
    status["Status"] = "Upcoming"
    status.loc[status["kickoff"] <= now, "Status"] = "Played / in progress"
    status.loc[status["Data"] == "Ready", "Status"] = "Scored"
    return status
