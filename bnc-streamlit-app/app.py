from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from config import POINTS_DIR, STAGE_LABELS, STAGES, WORKBOOK_PATH
from github_storage import upload_file
from league_data import build_league_data, due_missing_matches, fixture_status
from match_batch import process_matches


st.set_page_config(
    page_title="BnC World Cup 2026",
    page_icon="⚽",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1400px;}
    [data-testid="stMetricValue"] {font-size: 2rem;}
    .bnc-kicker {color: #5f6b75; font-size: .88rem; font-weight: 700;
                 letter-spacing: .12em; text-transform: uppercase;}
    .bnc-title {font-size: 2.75rem; font-weight: 800; line-height: 1.05;
                margin: .2rem 0 .5rem;}
    .bnc-subtitle {color: #5f6b75; font-size: 1.05rem; margin-bottom: 1.4rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def github_settings() -> tuple[str, str, str]:
    repository = os.getenv("BNC_GITHUB_REPOSITORY", "")
    token = os.getenv("BNC_GITHUB_TOKEN", "")
    branch = os.getenv("BNC_GITHUB_BRANCH", "main")
    try:
        repository = st.secrets.get("BNC_GITHUB_REPOSITORY", repository)
        token = st.secrets.get("BNC_GITHUB_TOKEN", token)
        branch = st.secrets.get("BNC_GITHUB_BRANCH", branch)
    except FileNotFoundError:
        pass
    return repository, token, branch


def format_points(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column in result:
            result[column] = result[column].astype(float).round(1)
    return result


data = build_league_data(WORKBOOK_PATH, POINTS_DIR)
missing_due = due_missing_matches(data.schedule, POINTS_DIR)
fixture_data = fixture_status(data.schedule, POINTS_DIR)
ready_count = int((fixture_data["Data"] == "Ready").sum())

st.markdown('<div class="bnc-kicker">WT Analysis</div>', unsafe_allow_html=True)
st.markdown('<div class="bnc-title">BnC World Cup 2026</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="bnc-subtitle">Live fantasy standings, stage lineups and match scoring.</div>',
    unsafe_allow_html=True,
)

metric_1, metric_2, metric_3, metric_4 = st.columns(4)
leader = data.league_table.iloc[0] if not data.league_table.empty else None
metric_1.metric("Current leader", leader["Manager"] if leader is not None else "No scores")
metric_2.metric("Leader points", f"{leader['Points']:.1f}" if leader is not None else "0.0")
metric_3.metric("Matches scored", f"{ready_count} / {len(data.schedule)}")
metric_4.metric("Ready to process", len(missing_due))

overview_tab, stages_tab, teams_tab, data_tab = st.tabs(
    ["League", "Stages", "Teams", "Match data"]
)

with overview_tab:
    st.subheader("Overall league table")
    league_display = format_points(data.league_table, ["Points"])
    st.dataframe(
        league_display,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Rank": st.column_config.NumberColumn(width="small"),
            "Manager": st.column_config.TextColumn(width="medium"),
            "Points": st.column_config.NumberColumn(format="%.1f"),
        },
    )

    stage_pivot = (
        data.stage_totals.pivot(index="Manager", columns="Stage", values="Points")
        .reindex(columns=STAGES)
        .fillna(0)
    )
    stage_pivot.columns = [STAGE_LABELS[column] for column in stage_pivot.columns]
    stage_pivot["Total"] = stage_pivot.sum(axis=1)
    stage_pivot = stage_pivot.sort_values("Total", ascending=False)

    st.subheader("Points by stage")
    st.dataframe(
        stage_pivot.round(1),
        use_container_width=True,
        column_config={
            column: st.column_config.NumberColumn(format="%.1f")
            for column in stage_pivot.columns
        },
    )
    st.bar_chart(stage_pivot.drop(columns="Total"), stack=True, height=420)

with stages_tab:
    selected_stage = st.selectbox(
        "Stage",
        STAGES,
        format_func=lambda value: STAGE_LABELS[value],
    )
    stage_totals = data.stage_totals[data.stage_totals["Stage"] == selected_stage].copy()
    stage_totals = stage_totals.sort_values("Points", ascending=False).reset_index(drop=True)
    stage_totals.insert(0, "Rank", range(1, len(stage_totals) + 1))

    left, right = st.columns([1, 2])
    with left:
        st.subheader(f"{STAGE_LABELS[selected_stage]} standings")
        st.dataframe(
            format_points(stage_totals, ["Points"]),
            hide_index=True,
            use_container_width=True,
        )
    with right:
        st.subheader("Manager comparison")
        chart_data = stage_totals.set_index("Manager")[["Points"]]
        st.bar_chart(chart_data, horizontal=True, height=420)

    st.subheader("Stage lineups")
    stage_lineups = data.lineup_scores[data.lineup_scores["Stage"] == selected_stage]
    manager_columns = st.columns(2)
    for index, manager in enumerate(data.league_table["Manager"]):
        with manager_columns[index % 2]:
            lineup = stage_lineups[stage_lineups["Manager"] == manager].copy()
            total = lineup["Lineup Points"].sum()
            st.markdown(f"#### {manager} · {total:.1f} pts")
            lineup = lineup[
                ["Position", "Player", "Selection", "Player Points", "Multiplier", "Lineup Points"]
            ]
            st.dataframe(
                format_points(lineup, ["Player Points", "Multiplier", "Lineup Points"]),
                hide_index=True,
                use_container_width=True,
                height=350,
            )

with teams_tab:
    manager = st.selectbox("Manager", list(data.league_table["Manager"]))
    manager_total = float(
        data.league_table.loc[data.league_table["Manager"] == manager, "Points"].iloc[0]
    )
    st.metric(f"{manager}'s total", f"{manager_total:.1f}")

    manager_stages = (
        data.stage_totals[data.stage_totals["Manager"] == manager]
        .set_index("Stage")
        .reindex(STAGES)
        .reset_index()
    )
    manager_stages["Stage"] = manager_stages["Stage"].map(STAGE_LABELS)
    st.dataframe(
        format_points(manager_stages[["Stage", "Points"]].fillna(0), ["Points"]),
        hide_index=True,
        use_container_width=True,
    )

    team_stage = st.selectbox(
        "Lineup stage",
        STAGES,
        format_func=lambda value: STAGE_LABELS[value],
        key="team_stage",
    )
    team_lineup = data.lineup_scores[
        (data.lineup_scores["Manager"] == manager)
        & (data.lineup_scores["Stage"] == team_stage)
    ][
        [
            "Position",
            "Player",
            "Selection",
            "Player Points",
            "Multiplier",
            "Lineup Points",
        ]
    ]
    st.dataframe(
        format_points(team_lineup, ["Player Points", "Multiplier", "Lineup Points"]),
        hide_index=True,
        use_container_width=True,
    )

with data_tab:
    st.subheader("Update match points")
    st.write(
        "The app processes fixtures after a 2.5-hour completion buffer. "
        "Existing point files are never recalculated by the batch button."
    )

    if missing_due.empty:
        st.success("All completed fixtures currently have point data.")
    else:
        due_display = missing_due[
            ["kickoff", "description", "Home_Team", "Away_Team", "Round", "matchlink"]
        ].copy()
        st.dataframe(due_display, hide_index=True, use_container_width=True)

        if st.button(
            f"Run {len(missing_due)} missing completed match(es)",
            type="primary",
            use_container_width=True,
        ):
            progress = st.progress(0, text="Starting match processing...")

            def update_progress(index: int, total: int, match_id: str) -> None:
                progress.progress(
                    index / total,
                    text=f"Processing {index} of {total}: {match_id}",
                )

            results = process_matches(missing_due, update_progress)
            repository, token, branch = github_settings()
            uploaded = []

            for result in results:
                if result["success"] and repository and token:
                    try:
                        uploaded.append(
                            upload_file(
                                result["path"],
                                repository=repository,
                                token=token,
                                branch=branch,
                            )
                        )
                    except Exception as exc:
                        result["error"] = f"Scored locally; GitHub upload failed: {exc}"

            st.session_state["processing_results"] = results
            st.session_state["uploaded_files"] = uploaded
            progress.empty()
            st.rerun()

    results = st.session_state.get("processing_results", [])
    if results:
        successes = sum(result["success"] for result in results)
        st.success(f"Processed {successes} of {len(results)} match(es).")
        failures = [result for result in results if result["error"]]
        if failures:
            st.warning("Some matches need attention.")
            st.dataframe(pd.DataFrame(failures)[["match_id", "error"]], hide_index=True)

    st.subheader("Fixture data status")
    stage_filter = st.multiselect("Filter stages", STAGES, default=STAGES)
    status_display = fixture_data[fixture_data["Round"].isin(stage_filter)][
        ["kickoff", "Fixture", "Round", "Status", "Data", "matchlink"]
    ].sort_values("kickoff", ascending=False)
    st.dataframe(
        status_display,
        hide_index=True,
        use_container_width=True,
        column_config={
            "kickoff": st.column_config.DatetimeColumn("Kickoff (UTC)", format="DD MMM YYYY, HH:mm"),
            "matchlink": st.column_config.TextColumn("Match ID"),
        },
    )

    repository, token, branch = github_settings()
    if repository and token:
        st.caption(f"GitHub persistence enabled for `{repository}` on `{branch}`.")
    else:
        st.info(
            "GitHub persistence is not configured. New files work immediately in this "
            "session but may be lost when Streamlit Cloud restarts."
        )
