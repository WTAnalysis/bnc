from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests


FEED_URL = (
    "https://api.performfeeds.com/soccerdata/matchevent/"
    "ft1tiv1inq7v1sk3y9tv12yh5/{match_id}"
    "?_rt=c&_lcl=en&_fmt=jsonp&sps=widgets&_clbk=bnc"
)
HEADERS = {
    "Referer": "https://www.scoresway.com/",
    "User-Agent": "Mozilla/5.0",
}
NON_LIVE_STATUSES = {
    "Fixture",
    "Played",
    "Postponed",
    "Cancelled",
    "Canceled",
    "Abandoned",
}


def candidate_matches(
    schedule: pd.DataFrame,
    now: datetime | None = None,
    before_hours: float = 5,
    after_hours: float = 2,
) -> pd.DataFrame:
    """Return fixtures close enough to now to warrant a provider status check."""
    now = now or datetime.now(timezone.utc)
    return schedule[
        schedule["kickoff"].between(
            now - timedelta(hours=before_hours),
            now + timedelta(hours=after_hours),
        )
    ].copy()


def fetch_match_status(match_id: str, timeout: int = 30) -> dict:
    response = requests.get(
        FEED_URL.format(match_id=match_id),
        headers=HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()
    match = re.search(r"\((.*)\)", response.text, flags=re.DOTALL)
    if match is None:
        raise ValueError(f"Unexpected response format for match {match_id}")
    data = json.loads(match.group(1))
    match_info = data.get("matchInfo", {})
    details = data.get("liveData", {}).get("matchDetails", {})
    contestants = match_info.get("contestant", [])
    home = next(
        (team.get("name") for team in contestants if team.get("position") == "home"),
        "Home",
    )
    away = next(
        (team.get("name") for team in contestants if team.get("position") == "away"),
        "Away",
    )
    scores = details.get("scores", {})
    current_score = scores.get("total") or scores.get("ft") or scores.get("ht") or {}
    status = details.get("matchStatus", "Unknown")
    provider_updated = pd.to_datetime(
        match_info.get("lastUpdated"),
        utc=True,
        errors="coerce",
    )
    checked_at = datetime.now(timezone.utc)

    return {
        "matchlink": match_id,
        "Fixture": match_info.get("description") or f"{home} vs {away}",
        "Home": home,
        "Away": away,
        "Home Score": current_score.get("home"),
        "Away Score": current_score.get("away"),
        "Provider Status": status,
        "Is Live": status not in NON_LIVE_STATUSES and status != "Unknown",
        "Is Complete": status == "Played",
        "Provider Updated UTC": (
            provider_updated.isoformat() if not pd.isna(provider_updated) else None
        ),
        "Checked At UTC": checked_at.isoformat(),
    }


def fetch_candidate_statuses(schedule: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    rows = []
    errors = []
    for row in candidate_matches(schedule).itertuples(index=False):
        match_id = str(row.matchlink).strip()
        try:
            status = fetch_match_status(match_id)
            status["Kickoff UTC"] = row.kickoff.isoformat()
            rows.append(status)
        except Exception as exc:
            errors.append({"matchlink": match_id, "error": str(exc)})
    return pd.DataFrame(rows), errors


def save_status_cache(statuses: pd.DataFrame, cache_path: Path) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(statuses.to_dict(orient="records"), indent=2),
        encoding="utf-8",
    )


def load_status_cache(cache_path: Path) -> pd.DataFrame:
    if not cache_path.exists():
        return pd.DataFrame()
    try:
        return pd.DataFrame(json.loads(cache_path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return pd.DataFrame()


def format_england_time(value: object) -> str:
    timestamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(timestamp):
        return "Not available"
    return timestamp.tz_convert(ZoneInfo("Europe/London")).strftime(
        "%d %b %Y, %H:%M:%S %Z"
    )
