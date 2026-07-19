from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from config import (
    MANAGER_SHEETS,
    MATCH_COMPLETION_BUFFER_HOURS,
    POINTS_OVERRIDE_PATH,
    SELECTION_MULTIPLIERS,
    STAGES,
    WC_BONUS_PATH,
)

POINTS_OVERRIDE_SHEET = "PointsOverride"
POINTS_OVERRIDE_COLUMNS = ["Manager", "Player", "player_id", "G1", "G2", "G3", "R2", "R3", "QF", "SF", "F", "Notes"]
WC_BONUS_MANAGER_COLUMN = "Manager"
WC_BONUS_PLAYER_COLUMN = "Player"
WC_BONUS_PLAYER_ID_COLUMN = "player_id"
WC_BONUS_ONE_OFF_MANAGER_BONUSES = {"Taylor": 10.0}
STAGE_ALIASES = {
    "g1": "G1",
    "g2": "G2",
    "g3": "G3",
    "r2": "Last 32",
    "last 32": "Last 32",
    "last32": "Last 32",
    "r3": "Last 16",
    "last 16": "Last 16",
    "last16": "Last 16",
    "qf": "Quarter Final",
    "quarter final": "Quarter Final",
    "sf": "Semi Final",
    "semi final": "Semi Final",
    "f": "3rd Place / Final",
    "final": "3rd Place / Final",
    "3rd place / final": "3rd Place / Final",
}


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


def normalize_player_key(value: object) -> str:
    return " ".join(str(value).strip().casefold().split())


def normalize_stage_label(value: object) -> str | None:
    key = str(value).strip().casefold()
    return STAGE_ALIASES.get(key)


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
    players["player_key"] = players["Player"].map(normalize_player_key)
    return players


def load_points_overrides(
    workbook_path: Path,
    override_path: Path | None = POINTS_OVERRIDE_PATH,
) -> pd.DataFrame:
    override_sources = []
    source_paths = [workbook_path]
    if override_path is not None:
        source_paths.append(override_path)

    for source_path in source_paths:
        try:
            overrides = pd.read_excel(source_path, sheet_name=POINTS_OVERRIDE_SHEET)
            override_sources.append(overrides)
        except (ValueError, FileNotFoundError):
            continue

    if not override_sources:
        return pd.DataFrame(columns=["Stage", "Player", "player_id", "Player Points"])

    overrides = pd.concat(override_sources, ignore_index=True)
    overrides.columns = [str(column).strip() for column in overrides.columns]
    if {"Stage", "Player Points"}.issubset(overrides.columns):
        result = overrides.copy()
        result["Stage"] = result["Stage"].map(normalize_stage_label)
        result["Player"] = result.get("Player", "").astype(str).str.strip()
        result["player_key"] = result["Player"].map(normalize_player_key)
        result["player_id"] = result.get("player_id", "").astype(str).str.strip()
        result["Player Points"] = pd.to_numeric(result["Player Points"], errors="coerce")
        result = result.dropna(subset=["Stage", "Player Points"])
        return result[["Stage", "Player", "player_key", "player_id", "Player Points"]].reset_index(drop=True)

    id_vars = [column for column in ["Manager", "Player", "player_id", "Notes"] if column in overrides.columns]
    stage_columns = [
        column for column in overrides.columns
        if normalize_stage_label(column) is not None
    ]
    if not stage_columns:
        return pd.DataFrame(columns=["Stage", "Player", "player_id", "Player Points"])

    result = overrides.melt(
        id_vars=id_vars,
        value_vars=stage_columns,
        var_name="Stage",
        value_name="Player Points",
    )
    result["Stage"] = result["Stage"].map(normalize_stage_label)
    result["Player"] = result.get("Player", "").astype(str).str.strip()
    result["player_key"] = result["Player"].map(normalize_player_key)
    result["player_id"] = result.get("player_id", "").astype(str).str.strip()
    result["Player Points"] = pd.to_numeric(result["Player Points"], errors="coerce")
    result = result.dropna(subset=["Stage", "Player Points"])
    result = result[
        result["Player"].str.lower().ne("nan") | result["player_id"].str.lower().ne("nan")
    ].copy()
    return result[["Stage", "Player", "player_key", "player_id", "Player Points"]].reset_index(drop=True)


def load_wc_bonus(
    bonus_path: Path | None = WC_BONUS_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    empty_player_bonus = pd.DataFrame(
        columns=["Manager", "Player", "player_id", "Player Bonus"]
    )
    empty_manager_bonus = pd.DataFrame(columns=["Manager", "Bonus"])
    if bonus_path is None or not bonus_path.exists():
        one_off = pd.DataFrame(
            [
                {"Manager": manager, "Bonus": float(points)}
                for manager, points in WC_BONUS_ONE_OFF_MANAGER_BONUSES.items()
            ]
        )
        return empty_player_bonus, one_off

    bonus = pd.read_excel(bonus_path)
    bonus.columns = [str(column).strip() for column in bonus.columns]
    if not {
        WC_BONUS_MANAGER_COLUMN,
        WC_BONUS_PLAYER_COLUMN,
        WC_BONUS_PLAYER_ID_COLUMN,
    }.issubset(bonus.columns):
        one_off = pd.DataFrame(
            [
                {"Manager": manager, "Bonus": float(points)}
                for manager, points in WC_BONUS_ONE_OFF_MANAGER_BONUSES.items()
            ]
        )
        return empty_player_bonus, one_off

    identity_columns = {
        WC_BONUS_MANAGER_COLUMN,
        WC_BONUS_PLAYER_COLUMN,
        WC_BONUS_PLAYER_ID_COLUMN,
    }
    numeric_columns = [
        column
        for column in bonus.columns
        if column not in identity_columns
        and pd.api.types.is_numeric_dtype(bonus[column])
    ]
    result = bonus.copy()
    result["Manager"] = result[WC_BONUS_MANAGER_COLUMN].map(normalize_manager)
    result["Player"] = result[WC_BONUS_PLAYER_COLUMN].astype(str).str.strip()
    result["player_id"] = result[WC_BONUS_PLAYER_ID_COLUMN].astype(str).str.strip()
    if numeric_columns:
        result["Player Bonus"] = (
            result[numeric_columns].apply(pd.to_numeric, errors="coerce").fillna(0.0).sum(axis=1)
        )
    else:
        result["Player Bonus"] = 0.0

    player_bonus = (
        result[
            result["Manager"].astype(str).str.strip().ne("")
            & result["Player"].astype(str).str.strip().ne("")
            & result["player_id"].astype(str).str.strip().ne("")
        ][["Manager", "Player", "player_id", "Player Bonus"]]
        .groupby(["Manager", "Player", "player_id"], as_index=False)["Player Bonus"]
        .sum()
    )

    manager_bonus = (
        player_bonus.groupby("Manager", as_index=False)["Player Bonus"]
        .sum()
        .rename(columns={"Player Bonus": "Bonus"})
    )
    one_off = pd.DataFrame(
        [
            {"Manager": manager, "Bonus": float(points)}
            for manager, points in WC_BONUS_ONE_OFF_MANAGER_BONUSES.items()
        ]
    )
    manager_bonus = (
        pd.concat([manager_bonus, one_off], ignore_index=True)
        .groupby("Manager", as_index=False)["Bonus"]
        .sum()
    )
    return player_bonus, manager_bonus


def apply_points_overrides(
    stage_points: pd.DataFrame,
    overrides: pd.DataFrame,
    players: pd.DataFrame,
) -> pd.DataFrame:
    if overrides.empty:
        return stage_points

    players = players.copy()
    if "player_key" not in players.columns:
        players["player_key"] = players["Player"].map(normalize_player_key)

    player_lookup = (
        players[["player_id", "Player", "player_key"]]
        .drop_duplicates(subset=["player_id"])
        .copy()
    )
    player_lookup["player_id"] = player_lookup["player_id"].astype(str).str.strip()
    player_lookup["Player"] = player_lookup["Player"].astype(str).str.strip()
    player_name_by_id = player_lookup.set_index("player_id")["Player"].to_dict()
    player_id_by_key = (
        player_lookup.dropna(subset=["player_key"])
        .drop_duplicates(subset=["player_key"])
        .set_index("player_key")["player_id"]
        .to_dict()
    )

    base = stage_points.copy()
    if "Player" not in base.columns:
        base = base.merge(player_lookup, on="player_id", how="left")
    base["player_id"] = base["player_id"].astype(str).str.strip()
    base["Player"] = base["Player"].astype(str).str.strip()
    base["override_key"] = base["Stage"].astype(str) + "||" + base["player_id"]
    base = base.set_index("override_key")

    overrides = overrides.copy()
    if "player_key" not in overrides.columns:
        overrides["player_key"] = overrides["Player"].map(normalize_player_key)
    overrides["player_id"] = overrides["player_id"].astype(str).str.strip()
    overrides["Player"] = overrides["Player"].astype(str).str.strip()

    unresolved = []
    for _, row in overrides.iterrows():
        stage = str(row["Stage"])
        player_id = str(row["player_id"]).strip()
        player_name = str(row["Player"]).strip()
        player_key = str(row["player_key"]).strip()
        points = float(row["Player Points"])

        resolved_id = player_id
        if not resolved_id or resolved_id.lower() == "nan":
            resolved_id = player_id_by_key.get(player_key, "")

        if not resolved_id or resolved_id.lower() == "nan":
            unresolved.append(
                {
                    "Stage": stage,
                    "player_id": "",
                    "Player": player_name,
                    "Player Points": points,
                }
            )
            continue

        key = f"{stage}||{resolved_id}"
        base.loc[key, "Stage"] = stage
        base.loc[key, "player_id"] = resolved_id
        base.loc[key, "Player"] = player_name or player_name_by_id.get(resolved_id, "")
        base.loc[key, "Player Points"] = points

    result = base.reset_index(drop=True)
    if unresolved:
        result = pd.concat([result, pd.DataFrame(unresolved)], ignore_index=True)
    return result[["Stage", "player_id", "Player", "Player Points"]]


def load_selections(workbook_path: Path, players: pd.DataFrame) -> pd.DataFrame:
    lookup = players.set_index(["Manager", "player_key"])["player_id"].to_dict()
    nation_lookup = players.set_index(["Manager", "player_key"])["Nation"].to_dict()
    rows: list[dict] = []

    for manager, sheet_name in MANAGER_SHEETS.items():
        sheet = pd.read_excel(workbook_path, sheet_name=sheet_name, header=None)
        for row_number in range(2, len(sheet)):
            player = str(sheet.iat[row_number, 1]).strip()
            if not player or player == "nan":
                continue
            player_key = normalize_player_key(player)
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
                        "Country": nation_lookup.get((manager, player_key), ""),
                        "player_id": lookup.get((manager, player_key), ""),
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
    player_bonus: pd.DataFrame | None = None,
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

    if player_bonus is not None and not player_bonus.empty:
        bonus_lookup = (
            player_bonus.groupby(["Manager", "player_id"], as_index=False)["Player Bonus"]
            .sum()
        )
        draft = draft.merge(
            bonus_lookup,
            on=["Manager", "player_id"],
            how="left",
        )
    else:
        draft["Player Bonus"] = 0.0
    draft["Player Bonus"] = draft["Player Bonus"].fillna(0.0)

    draft["Total"] = draft[STAGES].sum(axis=1) + draft["Player Bonus"]
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
    stage_points = apply_points_overrides(
        stage_points=stage_points,
        overrides=load_points_overrides(workbook_path),
        players=players,
    )
    player_bonus, manager_bonus = load_wc_bonus()
    lineup = selections.merge(
        stage_points[["Stage", "player_id", "Player Points"]],
        on=["Stage", "player_id"],
        how="left",
    )
    lineup["Player Points"] = lineup["Player Points"].fillna(0.0)
    lineup["Lineup Points"] = lineup["Player Points"] * lineup["Multiplier"]

    totals = (
        lineup.groupby(["Manager", "Stage"], as_index=False)["Lineup Points"]
        .sum()
        .rename(columns={"Lineup Points": "Points"})
    )
    totals["Stage"] = pd.Categorical(totals["Stage"], categories=STAGES, ordered=True)
    totals = totals.sort_values(["Stage", "Points", "Manager"], ascending=[True, False, True])

    draft_round_scores = build_draft_round_scores(players, stage_points, player_bonus)
    draft_bonus = (
        draft_round_scores[draft_round_scores["Draft Rank"] == 1]
        .groupby("Manager", as_index=False)["Bonus"]
        .sum()
    )

    fantasy_totals = (
        totals.groupby("Manager", as_index=False)["Points"]
        .sum()
    )
    league = fantasy_totals.merge(manager_bonus, on="Manager", how="left")
    league = league.merge(
        draft_bonus.rename(columns={"Bonus": "Draft Bonus"}),
        on="Manager",
        how="left",
    )
    league["Bonus"] = league["Bonus"].fillna(0.0) + league["Draft Bonus"].fillna(0.0)
    league = league.drop(columns=["Draft Bonus"])
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
