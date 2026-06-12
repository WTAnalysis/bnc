from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import streamlit as st

from config import (
    ONEDRIVE_SHARE_URL,
    PLAYERLIST_PATH,
    SCORE_COLUMNS,
    SCORES_PATH,
    STAGES,
)
from github_store import commit_scores
from scoring import score_match
from workbook_data import download_competition_workbook, matches_to_process, read_workbook

st.set_page_config(
    page_title="BnC World Cup Fantasy",
    page_icon="⚽",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container {max-width: 1320px; padding-top: 2rem;}
    [data-testid="stMetricValue"] {font-size: 2rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default))
    except FileNotFoundError:
        return default


@st.cache_data(ttl=300, show_spinner="Loading the live competition workbook...")
def load_live_workbook(download_url: str):
    workbook_bytes = download_competition_workbook(download_url)
    return read_workbook(workbook_bytes)


@st.cache_data(ttl=120)
def load_scores(path: str) -> pd.DataFrame:
    score_path = Path(path)
    if not score_path.exists() or score_path.stat().st_size == 0:
        return pd.DataFrame(columns=SCORE_COLUMNS)
    return pd.read_csv(score_path, dtype={"match_id": str, "player_id": str})


@st.cache_data
def load_playerlist() -> pd.DataFrame:
    return pd.read_excel(PLAYERLIST_PATH).dropna(subset=["player_id"])


def score_views(
    scores: pd.DataFrame,
    selections: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    active = selections[selections["active"] & selections["player_id"].notna()].copy()
    merged = active.merge(
        scores,
        on=["player_id", "stage"],
        how="left",
        suffixes=("", "_score"),
    )
    merged["points"] = pd.to_numeric(merged["points"], errors="coerce").fillna(0)
    merged["fantasy_points"] = merged["points"] * merged["multiplier"]

    stage_scores = (
        merged.groupby(["competitor", "stage"], as_index=False)["fantasy_points"]
        .sum()
    )
    table = (
        stage_scores.pivot(index="competitor", columns="stage", values="fantasy_points")
        .reindex(columns=STAGES, fill_value=0)
        .fillna(0)
    )
    table["Total"] = table.sum(axis=1)
    table = table.sort_values(["Total"], ascending=False).reset_index()
    table.insert(0, "Rank", range(1, len(table) + 1))
    return table, merged


st.title("BnC World Cup Fantasy")
st.caption("Live selections from OneDrive, completed match scores cached in GitHub.")

download_url = secret("ONEDRIVE_DOWNLOAD_URL", ONEDRIVE_SHARE_URL)
try:
    schedule, picked_players, selections = load_live_workbook(download_url)
except Exception as exc:
    st.error(str(exc))
    st.info(
        "The supplied OneDrive link currently requires Microsoft authentication. "
        "Change its sharing permission to 'Anyone with the link', then put the direct "
        "download URL in `.streamlit/secrets.toml` as `ONEDRIVE_DOWNLOAD_URL`."
    )
    st.stop()

scores = load_scores(str(SCORES_PATH))
league_table, selected_scores = score_views(scores, selections)

completed_matches = scores["match_id"].nunique() if not scores.empty else 0
latest_update = (
    pd.to_datetime(scores["processed_at"], errors="coerce", utc=True).max()
    if not scores.empty
    else pd.NaT
)
col1, col2, col3 = st.columns(3)
col1.metric("Competitors", 8)
col2.metric("Matches scored", completed_matches)
col3.metric(
    "Last score update",
    latest_update.strftime("%d %b %H:%M UTC") if pd.notna(latest_update) else "Not yet",
)

overview_tab, *stage_tabs, match_tab = st.tabs(
    ["League Table", *STAGES, "Match Scores"]
)

with overview_tab:
    st.subheader("League Table")
    st.dataframe(
        league_table,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Total": st.column_config.NumberColumn(format="%.1f"),
            **{
                stage: st.column_config.NumberColumn(format="%.1f")
                for stage in STAGES
            },
        },
    )
    st.caption("Captain scores are doubled. Bench selections beginning with 'Sub' score zero.")

for tab, stage in zip(stage_tabs, STAGES):
    with tab:
        st.subheader(stage)
        stage_summary = (
            league_table[["competitor", stage]]
            .rename(columns={"competitor": "Competitor", stage: "Points"})
            .sort_values("Points", ascending=False)
            .reset_index(drop=True)
        )
        stage_summary.insert(0, "Rank", range(1, len(stage_summary) + 1))
        st.dataframe(stage_summary, hide_index=True, use_container_width=True)

        detail = selected_scores[selected_scores["stage"] == stage].copy()
        detail = detail[[
            "competitor", "player", "position", "selection", "fixture",
            "minutes", "points", "multiplier", "fantasy_points",
        ]].rename(columns={
            "competitor": "Competitor",
            "player": "Player",
            "position": "Position",
            "selection": "Selection",
            "fixture": "Match",
            "minutes": "Minutes",
            "points": "Raw Points",
            "multiplier": "Multiplier",
            "fantasy_points": "Fantasy Points",
        })
        detail = detail[detail["Match"].notna()].sort_values(
            ["Fantasy Points", "Competitor"], ascending=[False, True]
        )
        st.dataframe(detail, hide_index=True, use_container_width=True)

with match_tab:
    st.subheader("Match Scores")
    if scores.empty:
        st.info("No completed matches have been processed yet.")
    else:
        match_options = (
            scores[["match_id", "match_datetime", "fixture", "stage"]]
            .drop_duplicates("match_id")
            .sort_values("match_datetime", ascending=False)
        )
        labels = {
            row.match_id: f"{row.fixture} | {row.stage} | {pd.to_datetime(row.match_datetime).strftime('%d %b %Y')}"
            for row in match_options.itertuples()
        }
        selected_match = st.selectbox(
            "Choose a completed match",
            match_options["match_id"],
            format_func=labels.get,
        )
        match_scores = scores[scores["match_id"] == selected_match].merge(
            selections[["competitor", "stage", "player_id", "selection", "active"]],
            on=["stage", "player_id"],
            how="inner",
        )
        match_scores = match_scores[match_scores["active"]].copy()
        st.dataframe(
            match_scores[[
                "competitor", "player_name", "team", "minutes", "selection",
                "goals", "assists", "defcons", "attcons", "points",
            ]].sort_values("points", ascending=False).rename(columns={
                "competitor": "Competitor",
                "player_name": "Player",
                "team": "Nation",
                "minutes": "Minutes",
                "selection": "Selection",
                "goals": "Goals",
                "assists": "Assists",
                "defcons": "DEFCONS",
                "attcons": "ATTCONS",
                "points": "Raw Points",
            }),
            hide_index=True,
            use_container_width=True,
        )

with st.sidebar:
    st.header("Score Admin")
    st.caption("Processes only unscored matches that kicked off 2 to 48 hours ago.")
    admin_password = st.text_input("Admin password", type="password")
    configured_password = secret("ADMIN_PASSWORD")
    can_sync = bool(configured_password) and admin_password == configured_password

    if st.button("Process recent matches", disabled=not can_sync, use_container_width=True):
        processed_ids = set(scores["match_id"].astype(str)) if not scores.empty else set()
        due = matches_to_process(schedule, processed_ids)
        if due.empty:
            st.success("No new matches need processing.")
        else:
            playerlist = load_playerlist()
            new_frames = []
            progress = st.progress(0)
            status = st.empty()
            for index, match in enumerate(due.itertuples(), start=1):
                status.write(f"Scoring {match.fixture}...")
                try:
                    new_frames.append(
                        score_match(
                            match.match_id,
                            playerlist,
                            match_datetime=match.match_datetime,
                            stage=match.stage,
                            fixture=match.fixture,
                        )
                    )
                except Exception as exc:
                    st.warning(f"{match.fixture}: {exc}")
                progress.progress(index / len(due))

            if new_frames:
                updated = pd.concat([scores, *new_frames], ignore_index=True)
                updated = updated.drop_duplicates(
                    ["match_id", "player_id"], keep="last"
                ).reindex(columns=SCORE_COLUMNS)
                SCORES_PATH.parent.mkdir(parents=True, exist_ok=True)
                updated.to_csv(SCORES_PATH, index=False)

                github_token = secret("GITHUB_TOKEN")
                github_repo = secret("GITHUB_REPO")
                github_branch = secret("GITHUB_BRANCH", "main")
                if github_token and github_repo:
                    url = commit_scores(
                        updated,
                        token=github_token,
                        repo=github_repo,
                        branch=github_branch,
                    )
                    st.success(f"Scores saved to GitHub: {url}")
                else:
                    st.warning(
                        "Scores were created locally, but GitHub secrets are not configured."
                    )
                st.cache_data.clear()
                st.rerun()

    st.divider()
    st.download_button(
        "Download score cache",
        data=scores.to_csv(index=False).encode("utf-8"),
        file_name="match_scores.csv",
        mime="text/csv",
        use_container_width=True,
    )
