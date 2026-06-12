from __future__ import annotations

import io
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import pandas as pd
import requests

from config import (
    COMPETITOR_NAMES,
    COMPETITOR_SHEETS,
    ONEDRIVE_SHARE_URL,
    STAGES,
)


def _normalise_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in text if not unicodedata.combining(char)).casefold().strip()


def _with_download_flag(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query["download"] = ["1"]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _is_xlsx(content: bytes) -> bool:
    return content[:4] == b"PK\x03\x04"


def download_competition_workbook(
    url: str = ONEDRIVE_SHARE_URL,
    *,
    timeout: int = 45,
) -> bytes:
    """Download an anonymously shared OneDrive workbook."""
    candidates = [url, _with_download_flag(url)]
    errors: list[str] = []

    for candidate in candidates:
        try:
            response = requests.get(
                candidate,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=timeout,
                allow_redirects=True,
            )
            if response.ok and _is_xlsx(response.content):
                return response.content
            errors.append(
                f"{response.status_code} from {response.url} "
                f"({response.headers.get('content-type', 'unknown content type')})"
            )
        except requests.RequestException as exc:
            errors.append(str(exc))

    raise RuntimeError(
        "The OneDrive workbook is not available as an anonymous XLSX download. "
        "Set ONEDRIVE_DOWNLOAD_URL in Streamlit secrets to an 'Anyone with the link' "
        "download URL. Attempts: " + " | ".join(errors)
    )


def read_workbook(
    workbook_bytes: bytes,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    source = io.BytesIO(workbook_bytes)
    schedule = pd.read_excel(source, sheet_name="schedule")
    source.seek(0)
    picked_players = pd.read_excel(source, sheet_name="PickedPlayers")

    selections: list[dict[str, object]] = []
    picked_players["_name_key"] = picked_players["Player"].map(_normalise_name)
    picked_lookup = (
        picked_players.dropna(subset=["player_id"])
        .drop_duplicates(["Manager", "_name_key"])
        .set_index(["Manager", "_name_key"])["player_id"]
        .to_dict()
    )

    for sheet_name in COMPETITOR_SHEETS:
        source.seek(0)
        sheet = pd.read_excel(source, sheet_name=sheet_name, header=None)
        competitor = COMPETITOR_NAMES[sheet_name]

        for row_index in range(2, min(18, len(sheet))):
            player = sheet.iat[row_index, 1] if sheet.shape[1] > 1 else None
            if pd.isna(player):
                continue
            name_key = _normalise_name(player)
            player_id = picked_lookup.get((competitor, name_key))

            for stage_index, stage in enumerate(STAGES):
                selection_col = 4 + stage_index * 3
                selection = (
                    sheet.iat[row_index, selection_col]
                    if selection_col < sheet.shape[1]
                    else None
                )
                label = "" if pd.isna(selection) else str(selection).strip()
                active = bool(label) and not label.casefold().startswith("sub")
                multiplier = 2.0 if label.casefold() == "captain" else 1.0 if active else 0.0
                selections.append(
                    {
                        "competitor": competitor,
                        "stage": stage,
                        "player_id": str(player_id).strip() if player_id else None,
                        "player": str(player).strip(),
                        "position": sheet.iat[row_index, 0],
                        "nation": sheet.iat[row_index, 2],
                        "selection": label,
                        "active": active,
                        "multiplier": multiplier,
                    }
                )

    return normalise_schedule(schedule), picked_players, pd.DataFrame(selections)


def normalise_schedule(schedule: pd.DataFrame) -> pd.DataFrame:
    result = schedule.copy()
    date_values = result["date"]
    if pd.api.types.is_numeric_dtype(date_values):
        dates = pd.to_datetime(date_values, unit="D", origin="1899-12-30")
    else:
        dates = pd.to_datetime(date_values, errors="coerce")

    times = result["time"].astype(str).str.extract(r"(\d{1,2}:\d{2}(?::\d{2})?)")[0]
    result["match_datetime"] = pd.to_datetime(
        dates.dt.strftime("%Y-%m-%d") + " " + times,
        errors="coerce",
        utc=True,
    )
    result["match_id"] = result["matchlink"].astype(str).str.strip()
    result["fixture"] = result["description"].fillna(
        result["Home_Team"].fillna("TBC").astype(str)
        + " vs "
        + result["Away_Team"].fillna("TBC").astype(str)
    )
    result["stage"] = result["Round"].astype(str).str.strip()
    return result[
        ["match_id", "fixture", "match_datetime", "stage", "Home_Team", "Away_Team"]
    ].dropna(subset=["match_datetime"])


def matches_to_process(
    schedule: pd.DataFrame,
    processed_ids: set[str],
    *,
    lookback_hours: int = 48,
    now: datetime | None = None,
) -> pd.DataFrame:
    current = now or datetime.now(timezone.utc)
    age_hours = (pd.Timestamp(current) - schedule["match_datetime"]).dt.total_seconds() / 3600
    mask = age_hours.between(2, lookback_hours, inclusive="both")
    return schedule.loc[mask & ~schedule["match_id"].isin(processed_ids)].sort_values(
        "match_datetime"
    )
