from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from config import LIVE_STATUS_PATH, POINTS_DIR, STAGE_LABELS, STAGES, WORKBOOK_PATH
from github_storage import upload_file
from league_data import (
    build_league_data,
    due_missing_matches,
    fixture_status,
    ordered_lineup,
)
from match_batch import process_matches
from live_scores import (
    fetch_candidate_statuses,
    fetch_statuses,
    format_england_time,
    load_status_cache,
    merge_status_cache,
    save_status_cache,
)
from predictions import (
    apply_live_scores,
    load_predictions,
    prediction_fixture_table,
    prediction_league_table,
)


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
    .stage-chart {height: 360px; display: flex; align-items: flex-end; gap: 2%;
                  position: relative; border-left: 1px solid #9aa39d;
                  border-bottom: 1px solid #9aa39d; padding: 0 2%;}
    .stage-grid {position: absolute; left: 0; right: 0; border-top: 1px dashed #cbd1cd;}
    .stage-grid.top {top: 0;} .stage-grid.middle {bottom: 50%;}
    .stage-bar-group {height: 100%; flex: 1; display: flex; flex-direction: column;
                      justify-content: flex-end; align-items: center; z-index: 1;}
    .stage-bar {height: 88%; width: 65%; display: flex; flex-direction: column-reverse;
                justify-content: flex-start;}
    .stage-segment {width: 100%; min-height: 0;}
    .stage-total {height: 6%; font-size: .8rem; font-weight: 700;}
    .stage-manager {height: 6%; font-size: .8rem; font-weight: 600; white-space: nowrap;}
    .chart-scale-label {font-size: .75rem; color: #5f6b75; margin-bottom: -12px;}
    .chart-zero {font-size: .75rem; color: #5f6b75; margin-top: -14px;}
    .stage-legend {display: flex; flex-wrap: wrap; gap: 12px; margin: 18px 0 22px;}
    .stage-legend span {font-size: .78rem; color: #465149;}
    .stage-legend i {display: inline-block; width: 10px; height: 10px;
                     margin-right: 5px; border-radius: 2px;}
    .horizontal-max {text-align: right; color: #5f6b75; font-size: .78rem;}
    .horizontal-chart {display: flex; flex-direction: column; gap: 14px; padding-top: 10px;}
    .horizontal-row {display: grid; grid-template-columns: 90px 1fr 45px;
                     gap: 10px; align-items: center;}
    .horizontal-name {font-size: .85rem; text-align: right;}
    .horizontal-track {height: 28px; background: #e3e8e4; border-radius: 3px; overflow: hidden;}
    .horizontal-bar {height: 100%; background: #0B6E4F;}
    .horizontal-value {font-size: .85rem; font-weight: 700;}
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


def persist_live_statuses(statuses: pd.DataFrame) -> str | None:
    save_status_cache(statuses, LIVE_STATUS_PATH)
    repository, token, branch = github_settings()
    if not repository or not token:
        return None
    return upload_file(
        LIVE_STATUS_PATH,
        repository=repository,
        token=token,
        branch=branch,
        remote_directory="bnc-streamlit-app/data",
    )


def format_points(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column in result:
            result[column] = result[column].astype(float).round(1)
    return result


CHART_COLORS = [
    "#0B6E4F",
    "#2A9D8F",
    "#78C6A3",
    "#E9C46A",
    "#F4A261",
    "#E76F51",
    "#577590",
    "#8E6C88",
]


def stacked_stage_chart_html(stage_table: pd.DataFrame) -> str:
    max_total = max(float(stage_table["Total"].max()), 1.0)
    stage_columns = [column for column in stage_table.columns if column != "Total"]
    bars = []
    for manager, row in stage_table.iterrows():
        segments = []
        for index, stage in enumerate(stage_columns):
            points = float(row[stage])
            height = (points / max_total) * 100
            segments.append(
                f'<div class="stage-segment" title="{stage}: {points:.1f}" '
                f'style="height:{height:.4f}%;background:{CHART_COLORS[index]}"></div>'
            )
        bars.append(
            '<div class="stage-bar-group">'
            f'<div class="stage-total">{float(row["Total"]):.1f}</div>'
            f'<div class="stage-bar">{"".join(segments)}</div>'
            f'<div class="stage-manager">{manager}</div>'
            "</div>"
        )
    legend = "".join(
        f'<span><i style="background:{CHART_COLORS[index]}"></i>{stage}</span>'
        for index, stage in enumerate(stage_columns)
    )
    return f"""
    <div class="chart-scale-label">{max_total:.1f}</div>
    <div class="stage-chart">
      <div class="stage-grid top"></div>
      <div class="stage-grid middle"></div>
      {"".join(bars)}
    </div>
    <div class="chart-zero">0</div>
    <div class="stage-legend">{legend}</div>
    """


def stage_comparison_chart_html(stage_totals: pd.DataFrame) -> str:
    max_score = max(float(stage_totals["Points"].max()), 1.0)
    bars = []
    for row in stage_totals.itertuples(index=False):
        width = (float(row.Points) / max_score) * 100
        bars.append(
            '<div class="horizontal-row">'
            f'<div class="horizontal-name">{row.Manager}</div>'
            '<div class="horizontal-track">'
            f'<div class="horizontal-bar" style="width:{width:.4f}%"></div>'
            "</div>"
            f'<div class="horizontal-value">{float(row.Points):.1f}</div>'
            "</div>"
        )
    return (
        f'<div class="horizontal-max">Scale: 0 to {max_score:.1f}</div>'
        f'<div class="horizontal-chart">{"".join(bars)}</div>'
    )


data = build_league_data(WORKBOOK_PATH, POINTS_DIR)
live_statuses = load_status_cache(LIVE_STATUS_PATH)
predictions = apply_live_scores(
    load_predictions(WORKBOOK_PATH),
    live_statuses,
)
prediction_table = prediction_league_table(predictions)
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

overview_tab, stages_tab, teams_tab, predictions_tab, data_tab = st.tabs(
    ["League", "Stages", "Teams", "Predictions", "Match data"]
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
    st.markdown(stacked_stage_chart_html(stage_pivot), unsafe_allow_html=True)

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
        st.markdown(stage_comparison_chart_html(stage_totals), unsafe_allow_html=True)

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

with predictions_tab:
    st.subheader("Predictions League Table")
    st.caption("Correct score = 3 points. Correct result = 1 point. Incorrect = 0 points.")
    live_prediction_rows = predictions[
        predictions["id"].astype(str).isin(
            set(live_statuses["matchlink"].astype(str))
            if not live_statuses.empty
            else set()
        )
        & predictions["Score"].notna()
    ]
    if not live_prediction_rows.empty:
        st.info(
            "The table includes the latest checked live score and is provisional "
            "until the match is complete."
        )
    st.dataframe(
        prediction_table,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Rank": st.column_config.NumberColumn(width="small"),
            "Points": st.column_config.NumberColumn(width="small"),
            "Correct Scores": st.column_config.NumberColumn(width="small"),
            "Correct Results": st.column_config.NumberColumn(width="small"),
        },
    )

    st.subheader("Scores and Predictions")
    prediction_rounds = [
        value for value in predictions["Round"].dropna().astype(str).unique()
    ]
    selected_prediction_rounds = st.multiselect(
        "Filter prediction rounds",
        prediction_rounds,
        default=prediction_rounds,
    )
    prediction_display = prediction_fixture_table(
        predictions[predictions["Round"].astype(str).isin(selected_prediction_rounds)]
    )
    st.dataframe(
        prediction_display,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Date": st.column_config.DateColumn(format="DD MMM YYYY"),
            "Time": st.column_config.TextColumn("Time (England)"),
        },
    )

with data_tab:
    st.subheader("Live matches")
    st.write(
        "Workbook kickoffs are UTC. The app displays live information in England "
        "time and uses the provider's match status rather than guessing from kickoff."
    )

    check_col, refresh_col = st.columns(2)
    with check_col:
        check_live = st.button(
            "Check live and recent scores",
            type="primary",
            use_container_width=True,
        )

    if check_live:
        with st.spinner("Checking live and recently completed fixtures..."):
            checked_statuses, live_errors = fetch_candidate_statuses(data.schedule)
            live_statuses = merge_status_cache(live_statuses, checked_statuses)
            try:
                persist_live_statuses(live_statuses)
            except Exception as exc:
                live_errors.append(
                    {
                        "matchlink": "live_status.json",
                        "error": f"Scores saved locally; GitHub upload failed: {exc}",
                    }
                )
            st.session_state["live_errors"] = live_errors
        st.rerun()

    live_matches = pd.DataFrame()
    if not live_statuses.empty:
        live_statuses["Is Live"] = live_statuses["Is Live"].fillna(False).astype(bool)
        live_matches = live_statuses[live_statuses["Is Live"]].copy()
        live_statuses["Score"] = live_statuses.apply(
            lambda row: (
                f"{int(row['Home Score'])}-{int(row['Away Score'])}"
                if pd.notna(row.get("Home Score")) and pd.notna(row.get("Away Score"))
                else "-"
            ),
            axis=1,
        )
        live_statuses["Kickoff (England)"] = live_statuses["Kickoff UTC"].map(
            format_england_time
        )
        live_statuses["Provider updated"] = live_statuses[
            "Provider Updated UTC"
        ].map(format_england_time)
        live_statuses["App checked"] = live_statuses["Checked At UTC"].map(
            format_england_time
        )

        st.dataframe(
            live_statuses[
                [
                    "Fixture",
                    "Kickoff (England)",
                    "Provider Status",
                    "Score",
                    "Provider updated",
                    "App checked",
                ]
            ],
            hide_index=True,
            use_container_width=True,
        )

        latest_check = live_statuses["Checked At UTC"].dropna()
        if not latest_check.empty:
            st.caption(
                "Live feed last checked by this app: "
                f"**{format_england_time(latest_check.max())}**"
            )

    if live_statuses.empty:
        st.info(
            "No score check has been saved yet. Click "
            "**Check live and recent scores** to fetch live or final scores."
        )
    elif live_matches.empty:
        st.info(
            "The provider does not currently report a fixture as live. "
            "Recently completed final scores are retained below."
        )
    else:
        st.success(
            f"{len(live_matches)} fixture(s) currently reported live. "
            "Fantasy points shown after refresh are provisional."
        )

    with refresh_col:
        refresh_live = st.button(
            "Refresh live fantasy points",
            disabled=live_matches.empty,
            use_container_width=True,
        )

    if refresh_live:
        progress = st.progress(0, text="Refreshing live fantasy points...")

        def update_live_progress(index: int, total: int, match_id: str) -> None:
            progress.progress(
                index / total,
                text=f"Refreshing {index} of {total}: {match_id}",
            )

        live_results = process_matches(
            live_matches[["matchlink"]],
            update_live_progress,
        )
        repository, token, branch = github_settings()
        for result in live_results:
            if result["success"] and repository and token:
                try:
                    upload_file(
                        result["path"],
                        repository=repository,
                        token=token,
                        branch=branch,
                    )
                except Exception as exc:
                    result["error"] = f"Scored locally; GitHub upload failed: {exc}"
        st.session_state["live_processing_results"] = live_results
        progress.empty()
        st.rerun()

    live_results = st.session_state.get("live_processing_results", [])
    if live_results:
        live_successes = sum(result["success"] for result in live_results)
        st.success(
            f"Refreshed provisional fantasy points for "
            f"{live_successes} of {len(live_results)} live match(es)."
        )
        live_failures = [result for result in live_results if result["error"]]
        if live_failures:
            st.warning("Some live matches could not be fully refreshed.")
            st.dataframe(
                pd.DataFrame(live_failures)[["match_id", "error"]],
                hide_index=True,
            )

    live_errors = st.session_state.get("live_errors", [])
    if live_errors:
        with st.expander("Live feed check warnings"):
            st.dataframe(pd.DataFrame(live_errors), hide_index=True)

    st.divider()
    st.subheader("Update match points")
    st.write(
        "The app processes fixtures after a 2.5-hour completion buffer. "
        "Existing point files are never recalculated by the batch button."
    )

    if missing_due.empty:
        st.success("All completed fixtures currently have point data.")
    else:
        due_display = missing_due[
            ["kickoff_uk", "description", "Home_Team", "Away_Team", "Round", "matchlink"]
        ].copy()
        st.dataframe(
            due_display,
            hide_index=True,
            use_container_width=True,
            column_config={
                "kickoff_uk": st.column_config.DatetimeColumn(
                    "Kickoff (England)",
                    format="DD MMM YYYY, HH:mm",
                ),
            },
        )

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
            checked_statuses, completed_status_errors = fetch_statuses(missing_due)
            live_statuses = merge_status_cache(live_statuses, checked_statuses)
            try:
                persist_live_statuses(live_statuses)
            except Exception as exc:
                completed_status_errors.append(
                    {
                        "matchlink": "live_status.json",
                        "error": f"Scores saved locally; GitHub upload failed: {exc}",
                    }
                )
            st.session_state["live_errors"] = completed_status_errors
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
    live_ids = (
        set(live_matches["matchlink"].astype(str))
        if not live_matches.empty
        else set()
    )
    visible_fixtures = fixture_data[
        fixture_data["Round"].isin(stage_filter)
        & (
            fixture_data["Data"].ne("Missing")
            | fixture_data["matchlink"].isin(live_ids)
        )
    ].copy()
    visible_fixtures["Provider Status"] = visible_fixtures["matchlink"].map(
        live_statuses.set_index("matchlink")["Provider Status"].to_dict()
        if not live_statuses.empty
        else {}
    )
    visible_fixtures["Score"] = visible_fixtures["matchlink"].map(
        live_statuses.set_index("matchlink")["Score"].to_dict()
        if not live_statuses.empty and "Score" in live_statuses
        else {}
    )
    visible_fixtures.loc[
        visible_fixtures["matchlink"].isin(live_ids), "Status"
    ] = "Live"
    status_display = visible_fixtures[
        [
            "kickoff_uk",
            "Fixture",
            "Round",
            "Status",
            "Provider Status",
            "Score",
            "Data",
            "matchlink",
        ]
    ].sort_values("kickoff_uk", ascending=False)
    st.dataframe(
        status_display,
        hide_index=True,
        use_container_width=True,
        column_config={
            "kickoff_uk": st.column_config.DatetimeColumn(
                "Kickoff (England)",
                format="DD MMM YYYY, HH:mm",
            ),
            "matchlink": st.column_config.TextColumn("Match ID"),
        },
    )

    scored_fixtures = visible_fixtures[visible_fixtures["Data"].ne("Missing")].copy()
    if not scored_fixtures.empty:
        st.subheader("Match player scores")
        scored_fixtures = scored_fixtures.sort_values("kickoff", ascending=False)
        match_options = scored_fixtures["matchlink"].tolist()
        fixture_labels = (
            scored_fixtures.set_index("matchlink")
            .apply(
                lambda row: (
                    f"{row['Fixture']} - "
                    f"{row['kickoff_uk'].strftime('%d %b %Y, %H:%M %Z')}"
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
