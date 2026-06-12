from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

import pandas as pd
import requests

from config import SCORE_COLUMNS

FEED_TEMPLATE = (
    "https://api.performfeeds.com/soccerdata/matchevent/"
    "ft1tiv1inq7v1sk3y9tv12yh5/{match_id}"
    "?_rt=c&_lcl=en&_fmt=jsonp&sps=widgets&_clbk=bnc"
)

EVENT_NAMES = {
    3: "dribbles",
    7: "tackles",
    8: "interceptions",
    10: "blocks_saves",
    12: "clearances",
    13: "miss",
    14: "post",
    15: "attempt_saved",
    16: "goal",
    17: "card",
    18: "player_off",
    19: "player_on",
    34: "team_setup",
    49: "ball_recoveries",
}


def _qualifiers(event: dict) -> dict[int, object]:
    return {
        int(item["qualifierId"]): item.get("value")
        for item in event.get("qualifier", [])
        if item.get("qualifierId") is not None
    }


def _absolute_minute(event: dict) -> float:
    # The Perform feed used here supplies cumulative event minutes. The source
    # notebook deliberately scores whole minutes from timeMin.
    return float(event.get("timeMin") or 0)


def fetch_match(match_id: str, timeout: int = 45) -> dict:
    response = requests.get(
        FEED_TEMPLATE.format(match_id=match_id),
        headers={
            "Referer": "https://www.scoresway.com/",
            "User-Agent": "Mozilla/5.0",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    match = re.search(r"\((.*)\)\s*$", response.text, re.DOTALL)
    if not match:
        raise ValueError("The match feed did not return valid JSONP.")
    return json.loads(match.group(1))


def _lineups(events: list[dict], player_names: dict[str, str]) -> list[dict]:
    rows: list[dict] = []
    for event in events:
        if int(event.get("typeId") or 0) != 34:
            continue
        qualifiers = _qualifiers(event)
        player_ids = [value.strip() for value in str(qualifiers.get(30, "")).split(",") if value.strip()]
        squad_numbers = [value.strip() for value in str(qualifiers.get(59, "")).split(",")]
        for index, player_id in enumerate(player_ids):
            rows.append(
                {
                    "player_id": player_id,
                    "player_name": player_names.get(player_id, player_id),
                    "team_id": str(event.get("contestantId") or ""),
                    "squad_number": squad_numbers[index] if index < len(squad_numbers) else "",
                    "starter": index < 11,
                    "time_on": 0.0 if index < 11 else None,
                    "time_off": None,
                }
            )
    return rows


def _fantasy_points(row: dict) -> float:
    position = row["position"]
    if position not in {"GK", "DEF", "MID", "FWD"}:
        return 0.0

    minutes = row["minutes"]
    goals = row["goals"]
    assists = row["assists"]
    conceded = row["goals_conceded"]
    score = 3 if minutes >= 120 else 2 if minutes >= 60 else 1 if minutes > 0 else 0

    if row["red_cards"] >= 1:
        score -= 3
    elif row["yellow_cards"] >= 1:
        score -= 1

    if position == "GK":
        score += goals * 20 + assists * 10 + row["blocks_saves"] * 0.5
        score -= conceded * 0.5
        if minutes >= 60 and conceded == 0:
            score += 4
        score += row["penalties_saved"] * 3
    elif position == "DEF":
        score += goals * 6 + assists * 4 - conceded * 0.5
        score += 3 if goals >= 3 else 0
        score += 3 if assists >= 3 else 0
        score += 2 if row["defcons"] >= 10 else 0
        score += 2 if row["attcons"] >= 10 else 0
        score += 4 if minutes >= 60 and conceded == 0 else 0
        score -= row["penalties_missed"] * 3 + row["own_goals"] * 3
    elif position == "MID":
        score += goals * 5 + assists * 3
        score += 3 if goals >= 3 else 0
        score += 3 if assists >= 3 else 0
        score += 2 if row["defcons"] >= 12 else 0
        score += 2 if row["attcons"] >= 10 else 0
        score += 1 if minutes >= 60 and conceded == 0 else 0
        score -= row["penalties_missed"] * 3 + row["own_goals"] * 3
    else:
        score += goals * 4 + assists * 3
        score += 3 if goals >= 3 else 0
        score += 3 if assists >= 3 else 0
        score += 2 if row["defcons"] >= 12 else 0
        score += 2 if row["attcons"] >= 10 else 0
        score -= row["penalties_missed"] * 3 + row["own_goals"] * 3
    return round(float(score), 2)


def score_match(
    match_id: str,
    playerlist: pd.DataFrame,
    *,
    match_datetime: object,
    stage: str,
    fixture: str,
    payload: dict | None = None,
) -> pd.DataFrame:
    data = payload or fetch_match(match_id)
    match_info = data["matchInfo"]
    live_data = data["liveData"]
    if live_data.get("matchDetails", {}).get("matchStatus") != "Played":
        raise ValueError(f"{fixture} is not marked as Played.")

    events = live_data.get("event", [])
    team_names = {
        str(team["id"]): team["name"] for team in match_info.get("contestant", [])
    }
    player_names = {
        str(event["playerId"]): str(event["playerName"])
        for event in events
        if event.get("playerId") and event.get("playerName")
    }
    lineups = _lineups(events, player_names)
    if not lineups:
        raise ValueError("No team setup events were found.")

    match_end = max(
        _absolute_minute(event)
        for event in events
        if int(event.get("periodId") or 0) in {1, 2, 3, 4}
    )
    lineup_by_id = {row["player_id"]: row for row in lineups}

    for event in events:
        player_id = str(event.get("playerId") or "")
        if player_id not in lineup_by_id:
            continue
        event_type = int(event.get("typeId") or 0)
        if event_type == 19:
            lineup_by_id[player_id]["time_on"] = _absolute_minute(event)
        elif event_type in {18, 20}:
            lineup_by_id[player_id]["time_off"] = _absolute_minute(event)
        elif event_type == 17 and set(_qualifiers(event)).intersection({32, 33}):
            lineup_by_id[player_id]["time_off"] = _absolute_minute(event)

    event_by_team_number = {
        (str(event.get("contestantId") or ""), str(event.get("eventId") or "")): event
        for event in events
    }
    goalkeeper_save_by_shot: dict[tuple[str, str], bool] = {}
    for event in events:
        if int(event.get("typeId") or 0) != 10:
            continue
        qualifiers = _qualifiers(event)
        shot_event_id = str(qualifiers.get(233) or "")
        if shot_event_id:
            goalkeeper_save_by_shot[
                (str(event.get("contestantId") or ""), shot_event_id)
            ] = 94 not in qualifiers
    counts: dict[str, Counter] = defaultdict(Counter)
    goal_events: list[tuple[float, str]] = []

    for event in events:
        player_id = str(event.get("playerId") or "")
        event_type = int(event.get("typeId") or 0)
        qualifiers = _qualifiers(event)
        metric = EVENT_NAMES.get(event_type)
        if player_id and metric in {
            "dribbles", "tackles", "interceptions", "blocks_saves",
            "clearances", "ball_recoveries",
        }:
            counts[player_id][metric] += 1

        if event_type == 17 and player_id:
            if 31 in qualifiers:
                counts[player_id]["yellow_cards"] += 1
            if 32 in qualifiers or 33 in qualifiers:
                counts[player_id]["red_cards"] += 1

        if event_type in {13, 14, 15, 16} and player_id:
            own_goal = event_type == 16 and 28 in qualifiers
            if event_type == 16 and not own_goal:
                counts[player_id]["goals"] += 1
            if own_goal:
                counts[player_id]["own_goals"] += 1
            if 9 in qualifiers and event_type != 16:
                counts[player_id]["penalties_missed"] += 1

            related_id = str(qualifiers.get(55) or "")
            related = event_by_team_number.get(
                (str(event.get("contestantId") or ""), related_id)
            )
            if related and related.get("playerId"):
                creator_id = str(related["playerId"])
                counts[creator_id]["key_passes"] += 1
                if event_type == 16 and not own_goal and (29 in qualifiers or 154 in qualifiers):
                    counts[creator_id]["assists"] += 1

            if event_type == 16 and not own_goal:
                counts[player_id]["shots_on_target"] += 1
            elif event_type == 15:
                opponent_team = next(
                    (
                        team_id
                        for team_id in team_names
                        if team_id != str(event.get("contestantId") or "")
                    ),
                    "",
                )
                if goalkeeper_save_by_shot.get(
                    (opponent_team, str(event.get("eventId") or "")),
                    False,
                ):
                    counts[player_id]["shots_on_target"] += 1

        if event_type == 10 and player_id and 9 in qualifiers:
            counts[player_id]["penalties_saved"] += 1

        if event_type == 16:
            scoring_team = str(event.get("contestantId") or "")
            if 28 in qualifiers:
                conceding_team = scoring_team
            else:
                conceding_team = next(
                    (team_id for team_id in team_names if team_id != scoring_team),
                    "",
                )
            goal_events.append((_absolute_minute(event), conceding_team))

    positions = (
        playerlist.dropna(subset=["player_id"])
        .assign(player_id=lambda frame: frame["player_id"].astype(str).str.strip())
        .drop_duplicates("player_id")
        .set_index("player_id")
    )
    output: list[dict] = []
    for player in lineups:
        player_id = player["player_id"]
        time_on = player["time_on"]
        if time_on is None:
            continue
        time_off = player["time_off"] if player["time_off"] is not None else match_end
        minutes = max(0.0, round(time_off - time_on, 2))
        player_counts = counts[player_id]
        position = (
            str(positions.at[player_id, "BnC Position"]).strip().upper()
            if player_id in positions.index
            else ""
        )
        goals_conceded = sum(
            1
            for goal_minute, conceding_team in goal_events
            if conceding_team == player["team_id"] and time_on <= goal_minute <= time_off
        )
        defcons_base = sum(
            player_counts[key]
            for key in ["clearances", "interceptions", "blocks_saves", "tackles"]
        )
        defcons = (
            0
            if position == "GK"
            else defcons_base
            if position == "DEF"
            else defcons_base + player_counts["ball_recoveries"]
        )
        attcons = sum(
            player_counts[key] for key in ["key_passes", "shots_on_target", "dribbles"]
        )
        row = {
            "match_id": match_id,
            "match_datetime": pd.Timestamp(match_datetime).isoformat(),
            "stage": stage,
            "fixture": fixture,
            "player_id": player_id,
            "player_name": player_names.get(player_id, player["player_name"]),
            "nation": positions.at[player_id, "Nation"] if player_id in positions.index else "",
            "team": team_names.get(player["team_id"], player["team_id"]),
            "minutes": minutes,
            **{key: int(player_counts[key]) for key in [
                "goals", "assists", "key_passes", "dribbles", "ball_recoveries",
                "clearances", "interceptions", "tackles", "blocks_saves",
                "shots_on_target", "yellow_cards", "red_cards", "own_goals",
                "penalties_missed", "penalties_saved",
            ]},
            "goals_conceded": goals_conceded,
            "defcons": defcons,
            "attcons": attcons,
            "position": position,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        row["points"] = _fantasy_points(row)
        output.append(row)

    frame = pd.DataFrame(output)
    return frame.reindex(columns=SCORE_COLUMNS)
