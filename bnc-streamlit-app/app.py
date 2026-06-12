from __future__ import annotations

import os

import altair as alt
import pandas as pd
import streamlit as st

from config import POINTS_DIR, STAGE_LABELS, STAGES, WORKBOOK_PATH
from github_storage import upload_file
from league_data import (
    build_league_data,
    due_missing_matches,
    fixture_status,
    ordered_lineup,
)
from match_batch import process_matches


st.set_page_config(
    page_title="BnC World Cup 2026",
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


def stacked_stage_chart(stage_table: pd.DataFrame) -> alt.Chart:
    chart_data = (
        stage_table.reset_index()
        .melt(id_vars=["Manager", "Total"], var_name="Stage", value_name="Points")
    )
    manager_order = stage_table.index.tolist()
    max_total = max(float(stage_table["Total"].max()), 1.0)
    return (
        alt.Chart(chart_data)
        .mark_bar()
        .encode(
            x=alt.X(
                "Manager:N",
                sort=manager_order,
                title=None,
                axis=alt.Axis(labelAngle=0),
            ),
            y=alt.Y(
                "sum(Points):Q",
                title="Points",
                scale=alt.Scale(domain=[0, max_total], nice=False),
            ),
            color=alt.Color("Stage:N", title="Stage"),
            order=alt.Order("Stage:N"),
            tooltip=[
                alt.Tooltip("Manager:N"),
                alt.Tooltip("Stage:N"),
                alt.Tooltip("Points:Q", format=".1f"),
            ],
        )
        .properties(height=420)
    )


def stage_comparison_chart(stage_totals: pd.DataFrame) -> alt.Chart:
    chart_data = stage_totals[["Manager", "Points"]].copy()
    manager_order = chart_data["Manager"].tolist()
    max_score = max(float(chart_data["Points"].max()), 1.0)
    return (
        alt.Chart(chart_data)
        .mark_bar()
        .encode(
            y=alt.Y("Manager:N", sort=manager_order, title=None),
            x=alt.X(
                "Points:Q",
                title="Points",
                scale=alt.Scale(domain=[0, max_score], nice=False),
            ),
            tooltip=[
                alt.Tooltip("Manager:N"),
                alt.Tooltip("Points:Q", format=".1f"),
            ],
        )
        .properties(height=420)
    )


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
    stage_pivot = (
        data.stage_totals.pivot(index="Manager", columns="Stage", values="Points")
        .reindex(columns=STAGES)
        .fillna(0)
    )
    stage_pivot.columns = [STAGE_LABELS[column] for column in stage_pivot.columns]
    stage_pivot["Total"] = stage_pivot.sum(axis=1)
    stage_pivot = stage_pivot.sort_values("Total", ascending=False)
    stage_columns = [column for column in stage_pivot.columns if column != "Total"]
    stage_pivot = stage_pivot[["Total"] + stage_columns]

    st.subheader("League Table")
    st.dataframe(
        stage_pivot.round(1),
        use_container_width=True,
        column_config={
            column: st.column_config.NumberColumn(format="%.1f")
            for column in stage_pivot.columns
        },
    )
    st.altair_chart(stacked_stage_chart(stage_pivot), use_container_width=True)

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
        st.altair_chart(stage_comparison_chart(stage_totals), use_container_width=True)

    st.subheader("Starting Lineups")
    stage_lineups = data.lineup_scores[data.lineup_scores["Stage"] == selected_stage]
    manager_columns = st.columns(2)
    for index, manager in enumerate(data.league_table["Manager"]):
        with manager_columns[index % 2]:
            lineup = ordered_lineup(
                stage_lineups[stage_lineups["Manager"] == manager].copy()
            )
            total = lineup["Lineup Points"].sum()
            st.markdown(f"#### {manager} - {total:.1f} pts")
            lineup = lineup[["Position", "Player", "Selection", "Player Points"]]
            st.dataframe(
                format_points(lineup, ["Player Points"]),
                hide_index=True,
                use_container_width=True,
                height=615,
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

    st.subheader("Starting Lineup")
    team_stage = st.selectbox(
        "Lineup stage",
        STAGES,
        format_func=lambda value: STAGE_LABELS[value],
        key="team_stage",
    )
    team_lineup = ordered_lineup(
        data.lineup_scores[
            (data.lineup_scores["Manager"] == manager)
            & (data.lineup_scores["Stage"] == team_stage)
        ]
    )[["Position", "Player", "Selection", "Player Points"]]
    st.dataframe(
        format_points(team_lineup, ["Player Points"]),
        hide_index=True,
        use_container_width=True,
        height=615,
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
    scored_fixtures = fixture_data[
        fixture_data["Round"].isin(stage_filter) & fixture_data["Data"].ne("Missing")
    ].copy()
    status_display = scored_fixtures[
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

    if not scored_fixtures.empty:
        st.subheader("Match player scores")
        scored_fixtures = scored_fixtures.sort_values("kickoff", ascending=False)
        match_options = scored_fixtures["matchlink"].tolist()
        fixture_labels = (
            scored_fixtures.set_index("matchlink")
            .apply(
                lambda row: (
                    f"{row['Fixture']} - "
                    f"{row['kickoff'].strftime('%d %b %Y, %H:%M UTC')}"
                ),
                axis=1,
            )
            .to_dict()
        )
        selected_match = st.selectbox(
            "Select a scored fixture",
            match_options,
            format_func=lambda match_id: fixture_labels[match_id],
        )
        match_scores = data.player_match_points[
            data.player_match_points["match_id"] == selected_match
        ].copy()
        manager_lookup = data.picked_players[
            ["player_id", "Manager"]
        ].drop_duplicates(subset="player_id")
        match_scores = match_scores.merge(manager_lookup, on="player_id", how="left")
        match_scores["Manager"] = match_scores["Manager"].fillna("Unowned")
        match_scores = (
            match_scores[match_scores["Total Score"] > 0]
            .sort_values(["Total Score", "player_name"], ascending=[False, True])
            .rename(
                columns={
                    "player_name": "Player",
                    "team_name": "Nation",
                    "Total Score": "Points",
                }
            )
        )
        if match_scores.empty:
            st.info("No players recorded a positive score in this match.")
        else:
            match_scores.insert(0, "Rank", range(1, len(match_scores) + 1))
            st.dataframe(
                format_points(
                    match_scores[["Rank", "Player", "Nation", "Manager", "Points"]],
                    ["Points"],
                ),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Points": st.column_config.NumberColumn(format="%.1f"),
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
