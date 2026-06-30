"""Match scoring engine adapted from ``BnC Streamlit App.ipynb``.

The calculation body is mechanically preserved from the notebook. The only
changes are parameterized paths, robust HTTP handling, batch-friendly output,
and removal of unused plotting imports.
"""

from pathlib import Path
import pandas as pd


REGULATION_PERIODS = {1, 2, 3, 4}
SHOOTOUT_PERIOD = 5


def regulation_period_mask(periods: pd.Series) -> pd.Series:
    return pd.to_numeric(periods, errors='coerce').isin(REGULATION_PERIODS)


def calculate_shootout_scores(events: pd.DataFrame) -> pd.DataFrame:
    """Return per-player shootout points from period 5 events only."""
    if events.empty:
        return pd.DataFrame(columns=['playerName', 'Shootout'])

    shootout_events = events.copy()
    shootout_events = shootout_events[
        pd.to_numeric(shootout_events.get('periodId'), errors='coerce').eq(SHOOTOUT_PERIOD)
    ].copy()
    if shootout_events.empty:
        return pd.DataFrame(columns=['playerName', 'Shootout'])

    shootout_events = shootout_events[shootout_events['typeId'] != 'goal_conceded'].copy()
    shootout_events = shootout_events.reset_index(drop=True)
    shootout_events['playerName'] = (
        shootout_events['playerName'].astype(str).str.strip()
    )
    shootout_events = shootout_events[
        shootout_events['playerName'].ne('')
        & shootout_events['playerName'].str.lower().ne('nan')
    ].copy()
    if shootout_events.empty:
        return pd.DataFrame(columns=['playerName', 'Shootout'])

    shot_points = {
        'Goal': 1,
        'Attempt Saved': -3,
        'Attempted Saved': -3,
        'Miss': -3,
        'Post': -3,
    }
    shooter_scores = shootout_events[
        shootout_events['typeId'].isin(shot_points)
    ][['playerName', 'typeId']].copy()
    shooter_scores['Shootout'] = shooter_scores['typeId'].map(shot_points).astype(int)
    shooter_scores = shooter_scores[['playerName', 'Shootout']]

    goalkeeper_rows: list[dict] = []
    for idx, row in shootout_events.iterrows():
        if row['typeId'] != 'Penalty faced':
            continue
        previous_type = shootout_events.iloc[idx - 1]['typeId'] if idx > 0 else None
        if previous_type == 'Goal':
            shootout_value = -1
        elif previous_type in {'Attempt Saved', 'Attempted Saved'}:
            shootout_value = 3
        else:
            shootout_value = 0
        goalkeeper_rows.append(
            {'playerName': row['playerName'], 'Shootout': shootout_value}
        )

    goalkeeper_scores = pd.DataFrame(goalkeeper_rows)
    combined = pd.concat(
        [shooter_scores, goalkeeper_scores],
        ignore_index=True,
    )
    if combined.empty:
        return pd.DataFrame(columns=['playerName', 'Shootout'])

    return combined.groupby('playerName', as_index=False)['Shootout'].sum()


def process_match(
    matchlink,
    output_dir,
    formation_dict_path,
    events_path,
    qualifiers_path,
    playerlist_path,
    request_timeout=45,
):
    """Download one completed match and write its per-player points workbook."""
    import requests
    import json
    import re
    import warnings
    from pandas.errors import SettingWithCopyWarning
    warnings.simplefilter(action="ignore", category=SettingWithCopyWarning)
    import pandas as pd
    import numpy as np 

    url = (
        'https://api.performfeeds.com/soccerdata/matchevent/'
        f'ft1tiv1inq7v1sk3y9tv12yh5/{matchlink}'
        '?_rt=c&_lcl=en&_fmt=jsonp&sps=widgets&_clbk=bnc'
    )
    headers = {
        'Referer': 'https://www.scoresway.com/',
        'User-Agent': 'Mozilla/5.0',
    }
    response = requests.get(url, headers=headers, timeout=request_timeout)
    response.raise_for_status()
    match = re.search(r'\((.*)\)', response.text, flags=re.DOTALL)
    if match is None:
        raise ValueError(f'Unexpected response format for match {matchlink}')
    data = json.loads(match.group(1))
    if 'liveData' not in data or 'matchInfo' not in data:
        raise ValueError(f'Match {matchlink} has no completed event data yet')
    matchevents = data['liveData']
    matchinfo = data['matchInfo']
    matchinfo_df = pd.json_normalize(matchinfo)
    teamdata = pd.json_normalize(matchinfo_df['contestant'].explode())
    # Select only the 'id' and 'name' columns
    teamdata = teamdata[['id', 'name']]

    # Display the resulting DataFrame

    hometeamid = teamdata.iloc[0, 0]
    awayteamid = teamdata.iloc[1, 0]
    matchevents_df = pd.json_normalize(matchevents)
    import pandas as pd
    events_expanded = pd.json_normalize(matchevents_df['event'].explode())
    def expand_qualifiers(row):
        # Each qualifier in the list will be expanded with index-based column names
        if isinstance(row, list):
            qualifiers_dict = {}
            for idx, qualifier in enumerate(row):
                for key, value in qualifier.items():
                    qualifiers_dict[f'qualifier/{idx}/{key}'] = value
            return pd.Series(qualifiers_dict)
        return pd.Series()  # Return an empty series if there are no qualifiers
    qualifiers_expanded = events_expanded['qualifier'].apply(expand_qualifiers)
    events_expanded = events_expanded.drop(columns=['qualifier']).join(qualifiers_expanded)
    df = events_expanded
    file_path = formation_dict_path
    formation_dict = pd.read_excel(file_path)

    import pandas as pd
    formation_rows = df[df['typeId'] == 34]
    formation_dfs = []
    for _, row in formation_rows.iterrows():
        row_data = row.to_dict()
        contestant_id = row_data.get('contestantId', None)
        qualifier_cols = [col for col in row.index if 'qualifierId' in col]
        formation_code = None
        player_ids = []
        squad_numbers = []
        formation_positions = []
        for col in qualifier_cols:
            try:
                qualifier_id = row[col]
                value_col = df.columns[df.columns.get_loc(col) + 1]
                value = row[value_col]
                if qualifier_id == 130:
                    formation_code = value
                elif qualifier_id == 30:
                    player_ids = str(value).split(',')
                elif qualifier_id == 59:
                    squad_numbers = str(value).split(',')
                elif qualifier_id == 131:
                    formation_positions = str(value).split(',')
            except:
                continue
        num_players = len(player_ids)
        data = {
            'formation_code': [formation_code] * num_players,
            'player_id': player_ids,
            'squad_number': squad_numbers,
            'formation_position': formation_positions,
            'is_starter': ['yes' if i < 11 else 'no' for i in range(num_players)],
            'contestant_id': [contestant_id] * num_players
        }
        formation_df = pd.DataFrame(data)
        formation_dfs.append(formation_df)
    formation_dfs = pd.concat(formation_dfs, ignore_index=True)
    player_lookup = df[['playerId', 'playerName']].dropna().drop_duplicates()
    formation_dfs['player_id'] = formation_dfs['player_id'].astype(str).str.strip()
    player_lookup['playerId'] = player_lookup['playerId'].astype(str).str.strip()
    formation_dfs = formation_dfs.merge(
        player_lookup,
        left_on='player_id',
        right_on='playerId',
        how='left'
    ).drop(columns=['playerId'])
    formation_dfs
    formation_dict['formation_code'] = formation_dict['formation_code'].astype(str).str.strip()
    formation_dict_melted = formation_dict.melt(
        id_vars='formation_code',
        var_name='formation_position',
        value_name='position'
    )
    formation_dfs = formation_dfs[formation_dfs['formation_position'].notna()].copy()
    formation_dfs['formation_position'] = formation_dfs['formation_position'].astype(float).astype(int).astype(str)
    formation_dict_melted['formation_position'] = formation_dict_melted['formation_position'].astype(str)
    formation_dfs = formation_dfs.merge(
        formation_dict_melted,
        on=['formation_code', 'formation_position'],
        how='left'
    )
    formation_dfs['match_id'] = matchlink
    formation_dfs.rename(columns={'playerName': 'player_name'}, inplace=True)
    starting_lineups = formation_dfs[
        [
            'match_id',
            'contestant_id',
            'player_name',
            'squad_number',
            'position',
            'is_starter',
            'formation_position',
            'player_id'
        ]
    ]
    ## STEP 5 - subs off
    subs_off = df[df['typeId'] == 18][['playerName', 'timeMin','periodId']].dropna()
    subs_off['playerName'] = subs_off['playerName'].astype(str).str.strip()
    starting_lineups['player_name'] = starting_lineups['player_name'].astype(str).str.strip()
    starting_lineups = starting_lineups.merge(
        subs_off,
        left_on='player_name',
        right_on='playerName',
        how='left'
    ).drop(columns=['playerName'])  # drop extra merge column
    starting_lineups.rename(columns={'timeMin': 'minutes_played'}, inplace=True)
    starting_lineups['subbed_off'] = starting_lineups['minutes_played'].apply(
        lambda x: 'yes' if pd.notna(x) else 'no'
    )

    ## STEP 6 - subs on
    subs_on = df[df['typeId'] == 19][['playerName', 'timeMin','periodId']].dropna()
    subs_on['playerName'] = subs_on['playerName'].astype(str).str.strip()
    max_time = df['timeMin'].max()
    subs_on['minutes_played'] = max_time - subs_on['timeMin']
    subs_on['subbed_on'] = 'yes'
    starting_lineups['player_name'] = starting_lineups['player_name'].astype(str).str.strip()
    starting_lineups = starting_lineups.merge(
        subs_on,
        left_on='player_name',
        right_on='playerName',
        how='left'
    ).drop(columns=['playerName'])
    starting_lineups['subbed_on'] = starting_lineups['subbed_on'].fillna('no')
    starting_lineups['minutes_played'] = starting_lineups['minutes_played_x'].combine_first(starting_lineups['minutes_played_y'])
    starting_lineups.drop(columns=['minutes_played_x', 'minutes_played_y'], inplace=True)

    ################### NEW STEP
    subs_on_events = df[df['typeId'] == 19][['playerId', 'playerName']].dropna().copy()
    subs_on_events['playerId'] = subs_on_events['playerId'].astype(str).str.strip()
    subs_on_events['playerName'] = subs_on_events['playerName'].astype(str).str.strip()
    subs_on_events['event_index'] = subs_on_events.index
    formation_changes = df[df['typeId'] == 40].copy()
    formation_updates = []

    if not formation_changes.empty:
        for _, row in formation_changes.iterrows():
            row_data = row.to_dict()
            contestant_id = row_data.get('contestantId', None)
            qualifier_cols = [col for col in row.index if 'qualifierId' in col]
            formation_code = None
            player_ids = []
            formation_positions = []

            for col in qualifier_cols:
                try:
                    qualifier_id = row[col]
                    value_col = df.columns[df.columns.get_loc(col) + 1]
                    value = row[value_col]
                    if qualifier_id == 130:
                        formation_code = str(value).strip()
                    elif qualifier_id == 30:
                        player_ids = str(value).split(',')
                    elif qualifier_id == 131:
                        formation_positions = str(value).split(',')
                except:
                    continue

            if formation_code and player_ids and formation_positions:
                for i, pid in enumerate(player_ids):
                    pid = pid.strip()
                    formation_position = str(i + 1)
                    formation_updates.append({
                        'player_id': pid,
                        'formation_code': formation_code,
                        'formation_position': formation_position
                    })

        if formation_updates:
            sub_positions_df = pd.DataFrame(formation_updates)
            sub_positions_df = sub_positions_df.merge(
                formation_dict_melted,
                on=['formation_code', 'formation_position'],
                how='left'
            )
        else:
            sub_positions_df = pd.DataFrame(columns=['player_id', 'formation_code', 'formation_position', 'position'])
    else:
        sub_positions_df = pd.DataFrame(columns=['player_id', 'formation_code', 'formation_position', 'position'])


    # Update starting_lineups with new positions (but only where position is missing)
    starting_lineups = starting_lineups.merge(
        sub_positions_df[['player_id', 'position']],
        on='player_id',
        how='left',
        suffixes=('', '_new')
    )
    starting_lineups['position'] = starting_lineups['position'].combine_first(starting_lineups['position_new'])
    starting_lineups.drop(columns=['position_new'], inplace=True)
    subs_on_events = df[df['typeId'] == 19][['playerId', 'playerName', 'contestantId']].dropna().copy()
    subs_on_events['playerId'] = subs_on_events['playerId'].astype(str).str.strip()
    subs_on_events['playerName'] = subs_on_events['playerName'].astype(str).str.strip()
    subs_on_events['event_index'] = subs_on_events.index

    for _, sub_on_row in subs_on_events.iterrows():
        idx = sub_on_row['event_index']
        team_id = sub_on_row['contestantId']
        sub_on_name = sub_on_row['playerName']

        # Find the immediately previous row with a sub-off event (typeId 18) from the same team
        for lookback in range(1, 6):
            if idx - lookback < 0:
                break
            prev_row = df.iloc[idx - lookback]
            if prev_row['typeId'] == 18 and prev_row['contestantId'] == team_id:
                sub_off_name = str(prev_row['playerName']).strip()

                # Find that subbed-off player in the starting lineup
                sub_off_row = starting_lineups[
                    (starting_lineups['player_name'] == sub_off_name) &
                    (starting_lineups['position'].notna())
                ]
                if sub_off_row.empty:
                    break

                inherited_position = sub_off_row.iloc[0]['position']

                # Assign to the subbed-on player if not already assigned
                mask = (
                    (starting_lineups['player_name'] == sub_on_name) &
                    (starting_lineups['subbed_on'] == 'yes') &
                    (starting_lineups['position'].isna())
                )
                if mask.any():
                    starting_lineups.loc[mask, 'position'] = inherited_position
                break  # stop after the first match
    ## STEP 7 - minute calc
    max_time = df['timeMin'].max()
    starting_lineups.loc[
        (starting_lineups['is_starter'] == 'yes') & (starting_lineups['subbed_off'] == 'no'),
        'minutes_played'
    ] = max_time
    starting_lineups = starting_lineups.loc[starting_lineups['player_name'] != 'nan']

    ## STEP 8 - sendings off
    cards = df[df['typeId'] == 17].copy()
    qualifier_cols = [col for col in cards.columns if 'qualifierId' in col]

    if not cards.empty:
        cards['is_sent_off'] = cards[qualifier_cols].apply(
            lambda row: any(q in [32, 33] for q in row.values if pd.notna(q)), axis=1
        )
        
        sent_off = cards[cards['is_sent_off']][['playerName', 'timeMin']].dropna().copy()
        sent_off.rename(columns={'playerName': 'player_name', 'timeMin': 'sent_off_min'}, inplace=True)
        sent_off['player_name'] = sent_off['player_name'].astype(str).str.strip()
    else:
        sent_off = pd.DataFrame(columns=['player_name', 'sent_off_min'])
    starting_lineups['player_name'] = starting_lineups['player_name'].astype(str).str.strip()
    starting_lineups = starting_lineups.merge(
        sent_off,
        on='player_name',
        how='left'
    )
    starting_lineups.loc[
        (starting_lineups['sent_off_min'].notna()) & (starting_lineups['is_starter'] == 'yes'),
        'minutes_played'
    ] = starting_lineups['sent_off_min']
    starting_lineups.loc[
        (starting_lineups['sent_off_min'].notna()) & (starting_lineups['is_starter'] == 'no'),
        'minutes_played'
    ] = starting_lineups['sent_off_min'] - starting_lineups['minutes_played']
    starting_lineups.drop(columns=['sent_off_min'], inplace=True)

    ## STEP 9 - player position changes
    from collections import defaultdict
    player_position_changes = defaultdict(set)
    formation_changes = df[df['typeId'] == 40].copy()
    for _, row in formation_changes.iterrows():
        row_data = row.to_dict()
        contestant_id = row_data.get('contestantId', None)
        qualifier_cols = [col for col in row.index if 'qualifierId' in col]
        formation_code = None
        player_ids = []
        formation_positions = []
        for col in qualifier_cols:
            try:
                qualifier_id = row[col]
                value_col = df.columns[df.columns.get_loc(col) + 1]
                value = row[value_col]
                if qualifier_id == 130:
                    formation_code = str(value).strip()
                elif qualifier_id == 30:
                    player_ids = str(value).split(',')
                elif qualifier_id == 131:
                    formation_positions = str(value).split(',')
            except:
                continue
        if not (formation_code and player_ids and formation_positions):
            continue
        formation_snapshot = pd.DataFrame({
            'formation_code': [formation_code] * len(player_ids),
            'player_id': [pid.strip() for pid in player_ids],
            'formation_position': [str(i + 1) for i in range(len(player_ids))],
            'contestant_id': [contestant_id] * len(player_ids)
        })
        formation_snapshot = formation_snapshot.merge(
            formation_dict_melted,
            on=['formation_code', 'formation_position'],
            how='left'
        )
        for _, player_row in formation_snapshot.iterrows():
            pid = player_row['player_id']
            new_pos = player_row['position']
            if pd.isna(new_pos):
                continue
            match = starting_lineups[
                (starting_lineups['player_id'] == pid) &
                (starting_lineups['contestant_id'] == contestant_id)
            ]
            if match.empty:
                continue
            current_pos = match.iloc[0]['position']
            if pd.isna(current_pos):
                continue
            if new_pos != current_pos:
                player_position_changes[pid].add(new_pos)
    starting_lineups['other_positions'] = starting_lineups['player_id'].apply(
        lambda pid: ', '.join(sorted(player_position_changes[pid])) if pid in player_position_changes else None
    )
    player_position_change_times = defaultdict(dict)
    for _, row in formation_changes.iterrows():
        row_data = row.to_dict()
        contestant_id = row_data.get('contestantId', None)
        time_min = row_data.get('timeMin', None)
        time_sec = row_data.get('timeSec', None)
        period_id = row_data.get('periodId', None)
        qualifier_cols = [col for col in row.index if 'qualifierId' in col]
        formation_code = None
        player_ids = []
        formation_positions = []
        for col in qualifier_cols:
            try:
                qualifier_id = row[col]
                value_col = df.columns[df.columns.get_loc(col) + 1]
                value = row[value_col]
                if qualifier_id == 130:
                    formation_code = str(value).strip()
                elif qualifier_id == 30:
                    player_ids = str(value).split(',')
                elif qualifier_id == 131:
                    formation_positions = str(value).split(',')
            except:
                continue
        if not (formation_code and player_ids and formation_positions):
            continue
        formation_snapshot = pd.DataFrame({
            'formation_code': [formation_code] * len(player_ids),
            'player_id': [pid.strip() for pid in player_ids],
            'formation_position': [str(i + 1) for i in range(len(player_ids))],
            'contestant_id': [contestant_id] * len(player_ids)
        })
        formation_snapshot = formation_snapshot.merge(
            formation_dict_melted,
            on=['formation_code', 'formation_position'],
            how='left'
        )
        for _, player_row in formation_snapshot.iterrows():
            pid = player_row['player_id']
            new_pos = player_row['position']

            if pd.isna(new_pos):
                continue
            match = starting_lineups[
                (starting_lineups['player_id'] == pid) &
                (starting_lineups['contestant_id'] == contestant_id)
            ]
            if match.empty or pd.isna(match.iloc[0]['position']):
                continue
            current_pos = match.iloc[0]['position']
            if new_pos != current_pos:
                if new_pos not in player_position_change_times[pid]:
                    player_position_change_times[pid][new_pos] = {
                        'periodId': period_id,
                        'timeMin': time_min,
                        'timeSec': time_sec
                    }
    initial_position_lookup = starting_lineups.set_index('player_id')['position'].dropna().to_dict()
    def is_before_or_equal(change_time, row_time):
        return (
            change_time['periodId'] < row_time['periodId'] or
            (
                change_time['periodId'] == row_time['periodId'] and
                (
                    change_time['timeMin'] < row_time['timeMin'] or
                    (
                        change_time['timeMin'] == row_time['timeMin'] and
                        change_time['timeSec'] <= row_time['timeSec']
                    )
                )
            )
        )
    def resolve_position(row):
        pid = str(row.get('playerId')).strip()
        if pid not in initial_position_lookup:
            return None
        current_time = {
            'periodId': row.get('periodId'),
            'timeMin': row.get('timeMin'),
            'timeSec': row.get('timeSec')
        }
        if pid not in player_position_change_times:
            return initial_position_lookup[pid]
        changes = player_position_change_times[pid]
        valid_changes = []
        for pos, change_time in changes.items():
            if is_before_or_equal(change_time, current_time):
                valid_changes.append((change_time, pos))
        if not valid_changes:
            return initial_position_lookup[pid]
        valid_changes.sort(key=lambda x: (x[0]['periodId'], x[0]['timeMin'], x[0]['timeSec']), reverse=True)
        return valid_changes[0][1]
    df['playing_position'] = df.apply(resolve_position, axis=1)
    max_match_time = starting_lineups['minutes_played'].max()

    position_change_rows = []
    player_name_map = starting_lineups.set_index('player_id')['player_name'].to_dict()
    team_name_map = starting_lineups.set_index('player_id')['contestant_id'].to_dict()

    # Loop through position changes and create new rows
    for pid, changes in player_position_change_times.items():
        player_name = player_name_map.get(pid, None)
        team_name = team_name_map.get(pid, None)
        for pos, time_info in changes.items():
            position_change_rows.append({
                'timeMin': time_info['timeMin'],
                'timeSec': time_info['timeSec'],
                'playerId': pid,
                'playerName': player_name,
                #'team_name': team_name,
                'typeId': 'position_change',
                'playing_position': pos,
                'periodId': time_info['periodId']
            })

    # Convert to DataFrame and append to df
    position_change_df = pd.DataFrame(position_change_rows)



    # Calculate time_on for subbed-on players
    # Detect red card events using typeId == 32 or 33 in any of the columns from 17th onward
    red_card_events = df.iloc[:, 16:]
    is_red_card = red_card_events.apply(lambda row: 32 in row.values or 33 in row.values, axis=1)
    red_card_df = df[is_red_card & (df['typeId'] == 'Card')]

    # Get red card minute for each player
    red_card_times = red_card_df.groupby('playerId')['timeMin'].min().to_dict()

    # Overwrite minutes_played with red card time for those players
    for idx, row in starting_lineups.iterrows():
        player_id = row['player_id']
        if player_id in red_card_times:
            starting_lineups.at[idx, 'minutes_played'] = red_card_times[player_id]
    starting_lineups['time_on'] = starting_lineups.apply(
        lambda row: max_match_time - row['minutes_played'] if row['subbed_on'] == 'yes' and pd.notna(row['minutes_played']) else None,
        axis=1
    )
    starting_lineups['time_off'] = starting_lineups.apply(
        lambda row: row['minutes_played']
        if row['is_starter'] == 'yes' and pd.notna(row['minutes_played']) and row['minutes_played'] != max_match_time
        else None,
        axis=1
    )
    starting_lineups['time_on'] = starting_lineups['time_on'].fillna(0)
    starting_lineups['time_off'] = starting_lineups['time_off'].fillna(max_match_time)

    red_card_events = df.iloc[:, 16:]  # 0-based index, so 16 is column 17
    is_red_card = red_card_events.apply(lambda row: 32 in row.values or 33 in row.values, axis=1)
    red_card_df = df[is_red_card & (df['typeId'] == 'Card')]

    # Get first red card time per player
    red_card_times = red_card_df[['playerId', 'timeMin']].groupby('playerId').min().to_dict()['timeMin']

    # Override time_off for red-carded players
    for idx, row in starting_lineups.iterrows():
        player_id = row['player_id']
        if player_id in red_card_times:
            starting_lineups.at[idx, 'time_off'] = red_card_times[player_id]
            
    starting_lineups.loc[(starting_lineups['time_on'] == 0) & (starting_lineups['subbed_off'] == 'yes'), 'time_off'] = starting_lineups['minutes_played']
    # New Step: Track duration in each position per player
    from collections import defaultdict

    # Collect all changes including the initial position
    position_timeline = defaultdict(list)

    for player_id, changes in player_position_change_times.items():
        # Add initial position and time 0
        initial_pos = initial_position_lookup.get(player_id)
        if initial_pos:
            position_timeline[player_id].append((0, initial_pos))  # Assume minute 0

        # Add sorted change times
        for pos, time_data in sorted(
            changes.items(),
            key=lambda x: (x[1]['periodId'], x[1]['timeMin'], x[1]['timeSec'])
        ):
            if time_data['timeMin'] is not None:
                position_timeline[player_id].append((time_data['timeMin'], pos))

    # Add end of match to each player's timeline
    for player_id, timeline in position_timeline.items():
        # Sort timeline just to be safe
        timeline = sorted(timeline, key=lambda x: x[0])
        updated = []
        for i in range(len(timeline)):
            start_time, pos = timeline[i]
            end_time = (
                timeline[i+1][0] if i+1 < len(timeline)
                else starting_lineups[starting_lineups['player_id'] == player_id]['minutes_played'].max()
            )
            duration = end_time - start_time
            updated.append((pos, duration))
        position_timeline[player_id] = updated[:5]  # Limit to 5 entries

    # Add to starting_lineups
    for i in range(5):
        pos_col = f'position{i+1}'
        min_col = f'position{i+1}mins'
        starting_lineups[pos_col] = None
        starting_lineups[min_col] = None

    for idx, row in starting_lineups.iterrows():
        player_id = row['player_id']
        match_id = row['match_id']
        player_changes = [r for r in position_change_rows if r['playerId'] == player_id]

        # Add initial position if not explicitly in change list
        if row['position'] and not any((r['timeMin'] == 0 and r['timeSec'] == 0) for r in player_changes):
            player_changes.insert(0, {
                'playerId': player_id,
                'playerName': row['player_name'],
                'typeId': 'position_change',
                'playing_position': row['position'],
                'timeMin': row['time_on'],  # use actual time on
                'timeSec': 0,
                'periodId': 1
            })

        # Sort chronologically
        player_changes.sort(key=lambda r: (r['periodId'], r['timeMin'], r['timeSec']))
        
        # Build list of minute marks
        change_times = [r['timeMin'] + r['timeSec'] / 60 for r in player_changes]
        end_min = row['time_off']
        change_times.append(end_min)

        # Assign positions and durations
        for i in range(min(5, len(change_times) - 1)):
            pos_col = f'position{i+1}'
            mins_col = f'position{i+1}mins'
            starting_lineups.at[idx, pos_col] = player_changes[i]['playing_position']
            starting_lineups.at[idx, mins_col] = round(change_times[i+1] - change_times[i], 1)

    ## EXTRA POSITION CODE

    df = df.sort_values(by=['periodId', 'timeMin', 'timeSec']).reset_index(drop=True)

    # Group changes per player
    from collections import defaultdict
    from datetime import timedelta

    player_changes = defaultdict(list)
    for row in position_change_rows:
        pid = row['playerId']
        player_changes[pid].append({
            'timeMin': row['timeMin'],
            'timeSec': row['timeSec'],
            'periodId': row['periodId'],
            'position': row['playing_position']
        })

    # Sort each player's changes by time
    for pid in player_changes:
        player_changes[pid].sort(key=lambda x: (x['periodId'], x['timeMin'], x['timeSec']))

    # Assign positions to df rows
    for pid, changes in player_changes.items():
        player_mask = df['playerId'] == pid
        player_df = df[player_mask]

        # Get the initial position from starting_lineups
        initial_pos = starting_lineups[starting_lineups['player_id'] == pid]['position']
        if initial_pos.empty or pd.isna(initial_pos.iloc[0]):
            continue
        initial_pos = initial_pos.iloc[0]

        # First period: from time_on or period start up to first change
        first_change = changes[0]
        condition = (
            player_mask &
            (
                (df['periodId'] < first_change['periodId']) |
                ((df['periodId'] == first_change['periodId']) & (
                    (df['timeMin'] < first_change['timeMin']) |
                    ((df['timeMin'] == first_change['timeMin']) & (df['timeSec'] < first_change['timeSec']))
                ))
            )
        )
        df.loc[condition, 'playing_position'] = initial_pos

        # Fill between changes
        for i in range(1, len(changes)):
            prev = changes[i-1]
            curr = changes[i]
            condition = (
                player_mask &
                (
                    (df['periodId'] > prev['periodId']) |
                    ((df['periodId'] == prev['periodId']) & (
                        (df['timeMin'] > prev['timeMin']) |
                        ((df['timeMin'] == prev['timeMin']) & (df['timeSec'] >= prev['timeSec']))
                    ))
                ) &
                (
                    (df['periodId'] < curr['periodId']) |
                    ((df['periodId'] == curr['periodId']) & (
                        (df['timeMin'] < curr['timeMin']) |
                        ((df['timeMin'] == curr['timeMin']) & (df['timeSec'] < curr['timeSec']))
                    ))
                )
            )
            df.loc[condition, 'playing_position'] = prev['position']

        # Fill from last change to end of match
        last = changes[-1]
        condition = (
            player_mask &
            (
                (df['periodId'] > last['periodId']) |
                ((df['periodId'] == last['periodId']) & (
                    (df['timeMin'] > last['timeMin']) |
                    ((df['timeMin'] == last['timeMin']) & (df['timeSec'] >= last['timeSec']))
                ))
            )
        )
        df.loc[condition, 'playing_position'] = last['position']


    #DF WORK
    import pandas as pd
    import numpy as np
    Events = pd.read_excel(events_path)
    qualifiers = pd.read_excel(qualifiers_path)
    #teamdata = pd.read_csv(r"C:\Users\will-\OneDrive\Documents\WT Analysis\Scoresway\Team Log\teamlog.csv")
    event_map = dict(zip(Events["Code"], Events["Event"]))
    qualifier_map = dict(zip(qualifiers["Code"], qualifiers["Qualifier"]))
    df = df.iloc[:, :100]
    if 'assist' not in df.columns:
        df['assist'] = 0  # or np.nan if you prefer missing values
    #df["typeId"] = df["typeId"].map(event_map)
    #qualifier_columns = [f'qualifier/{i}/qualifierId' for i in range(16)]
    #df[qualifier_columns] = df[qualifier_columns].applymap(lambda x: qualifier_map.get(x, x))
    #df['outcome'] = df['outcome'].replace({0: 'Unsuccessful', 1: 'Successful'})
    #df.rename(columns={'contestantId': 'team_name'}, inplace=True)
    df["typeId"] = df["typeId"].map(event_map).fillna(df["typeId"])


    import re

    # Build lookup from starting_lineups
    player_name_lookup = (
        starting_lineups[['player_id', 'player_name']]
        .dropna(subset=['player_id'])
        .drop_duplicates()
        .copy()
    )
    player_name_lookup['player_id'] = player_name_lookup['player_id'].astype(str).str.strip()
    player_name_lookup = player_name_lookup.set_index('player_id')['player_name'].to_dict()

    qualifier_slots = sorted({
        int(m.group(1))
        for col in df.columns
        for m in [re.match(r'qualifier/(\d+)/qualifierId', col)]
        if m
    })

    offside_rows = []

    for idx, row in df.iterrows():
        for i in qualifier_slots:
            qid_col = f'qualifier/{i}/qualifierId'
            val_col = f'qualifier/{i}/value'

            if qid_col not in df.columns:
                continue

            qid = row.get(qid_col, pd.NA)
            if pd.isna(qid):
                continue

            # raw feed values are numeric here
            try:
                is_offside = float(qid) == 7.0
            except:
                is_offside = str(qid).strip().lower() == 'offside'

            if not is_offside:
                continue

            offside_player_id = row.get(val_col, pd.NA)
            if pd.isna(offside_player_id):
                continue

            offside_player_id = str(offside_player_id).strip()
            if offside_player_id.endswith('.0'):
                offside_player_id = offside_player_id[:-2]

            offside_rows.append({
                'id': row.get('id', pd.NA),
                'eventId': f"{row.get('eventId', idx)}_offside",
                'typeId': 'Offside',
                'periodId': row.get('periodId', pd.NA),
                'timeMin': row.get('timeMin', pd.NA),
                'timeSec': row.get('timeSec', pd.NA),
                'contestantId': row.get('contestantId', pd.NA),
                'outcome': 'Successful',
                'x': row.get('end_x', pd.NA),
                'y': row.get('end_y', pd.NA),
                'timeStamp': row.get('timeStamp', pd.NA),
                'lastModified': row.get('lastModified', pd.NA),
                'playerId': offside_player_id,
                'playerName': player_name_lookup.get(offside_player_id, pd.NA),
                'keyPass': 0
            })

            break

    if offside_rows:
        offside_df = pd.DataFrame(offside_rows)

        # align columns to raw df before concat
        for col in df.columns:
            if col not in offside_df.columns:
                offside_df[col] = pd.NA

        offside_df = offside_df[df.columns]
        df = pd.concat([df, offside_df], ignore_index=True, sort=False)





    # Build the requested qualifier column names
    qualifier_columns_requested = [f"qualifier/{i}/qualifierId" for i in range(16)]
    # Keep only the qualifier columns that actually exist in the DataFrame
    existing_qualifier_cols = [c for c in qualifier_columns_requested if c in df.columns]
    qualifier_columns = existing_qualifier_cols

    # Map values only on the existing subset
    if existing_qualifier_cols:
        df[existing_qualifier_cols] = df[existing_qualifier_cols].applymap(
            lambda x: qualifier_map.get(x, x)
        )
    # The rest of your transformations
    df["outcome"] = df["outcome"].replace({0: "Unsuccessful", 1: "Successful"})
    df.rename(columns={"contestantId": "team_name"}, inplace=True)
    df = df.merge(teamdata[['id', 'name']], how='left', left_on='team_name', right_on='id')
    df.drop(columns=['team_name', 'id_y'], inplace=True)
    df.rename(columns={'name': 'team_name', 'id_x': 'id'}, inplace=True)
    #df['end_x'] = 0  # Initialize with default values
    #df['end_y'] = 0
    #for i in range(16):
    #    end_x_mask = df[f'qualifier/{i}/qualifierId'] == 'Pass End X'
    #    end_y_mask = df[f'qualifier/{i}/qualifierId'] == 'Pass End Y'
    #    df.loc[end_x_mask, 'end_x'] = df.loc[end_x_mask, f'qualifier/{i}/value']
    #    df.loc[end_y_mask, 'end_y'] = df.loc[end_y_mask, f'qualifier/{i}/value']
    #df['end_x'] = pd.to_numeric(df['end_x'], errors='coerce').fillna(0)
    #df['end_y'] = pd.to_numeric(df['end_y'], errors='coerce').fillna(0)
    import re

    # Ensure these columns exist
    if 'end_x' not in df.columns:
        df['end_x'] = pd.NA
    if 'end_y' not in df.columns:
        df['end_y'] = pd.NA

    # Dynamically determine max qualifier index
    qualifier_indices = [
        int(match.group(1)) for col in df.columns
        if (match := re.match(r'qualifier/(\d+)/', col))
    ]
    max_index = max(qualifier_indices, default=0)

    # Loop over present qualifier slots
    for i in range(max_index + 1):
        value_col = f'qualifier/{i}/value'
        id_col = f'qualifier/{i}/qualifierId'

        if value_col not in df.columns or id_col not in df.columns:
            continue

        end_x_mask = df[id_col] == 'Pass End X'
        end_y_mask = df[id_col] == 'Pass End Y'

        df.loc[end_x_mask, 'end_x'] = pd.to_numeric(df.loc[end_x_mask, value_col], errors='coerce')
        df.loc[end_y_mask, 'end_y'] = pd.to_numeric(df.loc[end_y_mask, value_col], errors='coerce')

    # Final clean up
    df['end_x'] = df['end_x'].fillna(0)
    df['end_y'] = df['end_y'].fillna(0)



    df['throwin'] = df[qualifier_columns].apply(lambda row: 'Throw-in' in row.values, axis=1).astype(int)
    df['corner'] = df[qualifier_columns].apply(lambda row: 'Corner taken' in row.values, axis=1).astype(int)
    df['freekick'] = df[qualifier_columns].apply(lambda row: 'Free-kick taken' in row.values, axis=1).astype(int)
    df['goalkick'] = df[qualifier_columns].apply(lambda row: 'Goal Kick' in row.values, axis=1).astype(int)
    df['cross'] = df[qualifier_columns].apply(lambda row: 'Cross' in row.values, axis=1).astype(int)
    df['longball'] = df[qualifier_columns].apply(lambda row: 'Long ball' in row.values, axis=1).astype(int)
    df['switch'] = df[qualifier_columns].apply(lambda row: 'Switch of play' in row.values, axis=1).astype(int)
    df['launch'] = df[qualifier_columns].apply(lambda row: 'Launch' in row.values, axis=1).astype(int)
    df['secondassist'] = df[qualifier_columns].apply(lambda row: '2nd assist' in row.values, axis=1).astype(int)
    df['head'] = df[qualifier_columns].apply(lambda row: 'Head' in row.values, axis=1).astype(int)
    df['leftfoot'] = df[qualifier_columns].apply(lambda row: 'Left footed' in row.values, axis=1).astype(int)
    df['rightfoot'] = df[qualifier_columns].apply(lambda row: 'Right footed' in row.values, axis=1).astype(int)
    df['otherbody'] = df[qualifier_columns].apply(lambda row: 'Other body part' in row.values, axis=1).astype(int)
    df['fastbreakshot'] = df[qualifier_columns].apply(lambda row: 'Fast break' in row.values, axis=1).astype(int)
    df['setpieceshot'] = df[qualifier_columns].apply(lambda row: 'Set piece' in row.values, axis=1).astype(int)
    df['freekickshot'] = df[qualifier_columns].apply(lambda row: 'Free kick' in row.values, axis=1).astype(int)
    df['cornershot'] = df[qualifier_columns].apply(lambda row: 'From corner' in row.values, axis=1).astype(int)
    df['throwinshot'] = df[qualifier_columns].apply(lambda row: 'Throw-in set piece' in row.values, axis=1).astype(int)
    df['dfreekickshot'] = df[qualifier_columns].apply(lambda row: 'Direct free' in row.values, axis=1).astype(int)
    df['penaltyshot'] = df[qualifier_columns].apply(lambda row: 'Penalty' in row.values, axis=1).astype(int)
    #df['owngoal'] = df[qualifier_columns].apply(lambda row: 'Own goal' in row.values, axis=1).astype(int)
    #df['owngoal'] = df[qualifier_columns].apply(lambda row: any(val in ['OWN_GOAL', 'Own goal'] for val in row.values), axis=1).astype(int)
    df['owngoal'] = df.iloc[:, 16:].apply(
        lambda row: any(
            isinstance(val, str) and val.strip().lower() in ['own goal', 'own_goal']
            for val in row.values
        ),
        axis=1
    ).astype(int)
    df.loc[df['owngoal'] == 1, 'typeId'] = 'Own Goal'
    df['bigchance'] = df[qualifier_columns].apply(lambda row: 'Big chance' in row.values, axis=1).astype(int)
    df['hitwoodwork'] = df[qualifier_columns].apply(lambda row: 'Hit woodwork' in row.values, axis=1).astype(int)
    df['lastman'] = df[qualifier_columns].apply(lambda row: 'Last line' in row.values, axis=1).astype(int)
    df['errorshot'] = df[qualifier_columns].apply(lambda row: 'Leading to attempt' in row.values, axis=1).astype(int)
    df['errorgoal'] = df[qualifier_columns].apply(lambda row: 'Leading to goal' in row.values, axis=1).astype(int)
    df['yellowcard'] = df[qualifier_columns].apply(lambda row: 'Yellow Card' in row.values, axis=1).astype(int)
    df['yellowcard2'] = df[qualifier_columns].apply(lambda row: 'Second yellow' in row.values, axis=1).astype(int)
    df['redcard'] = df[qualifier_columns].apply(lambda row: 'Red Card' in row.values, axis=1).astype(int)
    df['shotblocked'] = df[qualifier_columns].apply(lambda row: 'Blocked' in row.values, axis=1).astype(int)

    df = df.loc[df['typeId'] !=40]
    df = df.loc[df['typeId'] !="Deleted event"]

    values_to_remove = ['Collection End', 'End', 'Team set up', 'Start']
    df = df[~df['typeId'].isin(values_to_remove)]
    columns_to_keep = ['id', 'eventId', 'typeId', 'periodId', 'timeMin', 'timeSec',
                       'team_name', 'outcome', 'x', 'y', 'end_x', 'end_y', 
                       'playerName','playing_position', 'keyPass', 'secondassist','assist',
                      'throwin','corner','freekick','goalkick','cross','longball','switch','launch',
                      'head','leftfoot','rightfoot','otherbody',
                      'fastbreakshot','setpieceshot','freekickshot','cornershot','throwinshot','dfreekickshot','penaltyshot','owngoal',
                       'bigchance','hitwoodwork','lastman','errorshot','errorgoal', 'yellowcard','yellowcard2','redcard','shotblocked']
    df = df[columns_to_keep]
    df['end_x'] = ((df['end_x'] - df['end_x'].min()) / (df['end_x'].max() - df['end_x'].min())) * 100
    df['end_y'] = ((df['end_y'] - df['end_y'].min()) / (df['end_y'].max() - df['end_y'].min())) * 100
    df.loc[df['owngoal'] == 1, 'typeId'] = 'Own Goal'
    # Shift playerName and team_name columns by -1 (next row)
    df['next_player'] = df['playerName'].shift(-1)
    df['next_team'] = df['team_name'].shift(-1)
    df['next_position'] = df['playing_position'].shift(-1)
            # Create pass_recipient only for successful passes to same team
    df['pass_recipient'] = np.where(
        (df['typeId'] == 'Pass') & 
        (df['outcome'] == 'Successful') & 
        (df['team_name'] == df['next_team']),
        df['next_player'],
        np.nan
        )
    df['pass_recipient_position'] = np.where(
        (df['typeId'] == 'Pass') & 
        (df['outcome'] == 'Successful') & 
        (df['team_name'] == df['next_team']),
        df['next_position'],
        np.nan
        )
    df = df[df['typeId'].notna()].reset_index(drop=True)
    mask = df['typeId'] == 'Ball recovery'
    df.loc[mask, 'end_x'] = df.loc[mask, 'x']
    df.loc[mask, 'end_y'] = df.loc[mask, 'y']


    df.loc[df['typeId'] == 'Offside', 'playing_position'] = (
        df.groupby('playerName')['playing_position']
          .ffill()
          .loc[df['typeId'] == 'Offside']
    )


    ##CARRY
    df['event_time'] = df['timeMin'] * 60 + df['timeSec']
    df = df.sort_values(by=['event_time', 'id']).reset_index(drop=True)
    carry_rows = []
    for i in range(len(df) - 1):
        current = df.iloc[i]
        current_team = current['team_name']
        current_player = current['playerName']
        end_x = current['end_x']
        end_y = current['end_y']
        current_type = current['typeId']
        current_outcome = current['outcome']
        is_pass = (current_type == 'Pass' and current_outcome == 'Successful')
        is_recovery = (current_type == 'Ball recovery' and current_outcome == 'Successful')
        is_interception = (current_type == 'Interception')
        is_take_on = (current_type == 'Take on' and current_outcome == 'Successful')
        if not (is_pass or is_recovery or is_interception or is_take_on):
            continue
        for j in range(i + 1, len(df)):
            next_row = df.iloc[j]
            if next_row['team_name'] != current_team:
                continue
            if (end_x == next_row['x']) and (end_y == next_row['y']):
                break
            if next_row['typeId'] == 'Aerial':
                break
            if (is_recovery or is_interception or is_take_on) and current_player != next_row['playerName']:
                break
            carry_row = current.copy()
            carry_row['id'] = current['id'] + 0.5
            carry_row['eventId'] = current['eventId'] + 0.5
            carry_row['typeId'] = 'Carry'
            carry_row['x'] = end_x
            carry_row['y'] = end_y
            carry_row['end_x'] = next_row['x']
            carry_row['end_y'] = next_row['y']
            carry_row['playerName'] = next_row['playerName']
            carry_row['playing_position'] = next_row['playing_position']
            carry_row['outcome'] = 'Successful'
            carry_rows.append(carry_row)
            break
    df = pd.concat([df, pd.DataFrame(carry_rows)], ignore_index=True)
    df = df.sort_values(by=['timeMin', 'timeSec', 'periodId']).reset_index(drop=True)
    df = df[~((df['typeId'] == 'Carry') & (df['x'] == 0) & (df['y'] == 0))].reset_index(drop=True)
    df = df[~((df['typeId'] == 'Carry') & (df['end_x'] == 0) & (df['end_y'] == 0))].reset_index(drop=True)
    to_delete = []
    for i in range(len(df) - 1):
        if df.iloc[i]['typeId'] == 'Carry' and df.iloc[i + 1]['typeId'] == 'Ball recovery':
            to_delete.append(i)  # Add the index of the 'Carry' row to delete
    df = df.drop(index=to_delete).reset_index(drop=True)
    df.loc[df['typeId'] == 'Carry', 'pass_recipient'] = np.nan
    carry_filter = ~(
        (df['typeId'] == 'Carry') &
        ((df['x'] - df['end_x']).abs() < 1.5) &
        ((df['y'] - df['end_y']).abs() < 2.5)
    )
    df = df[carry_filter]
    df.loc[df['typeId'] == 'Carry', ['keyPass', 'assist']] = np.nan
    #XTHREAT
    xT = np.array([[0.00638303, 0.00779616, 0.00844854, 0.00977659, 0.01126267,
                            0.01248344, 0.01473596, 0.0174506 , 0.02122129, 0.02756312,
                            0.03485072, 0.0379259 ],
                           [0.00750072, 0.00878589, 0.00942382, 0.0105949 , 0.01214719,
                            0.0138454 , 0.01611813, 0.01870347, 0.02401521, 0.02953272,
                            0.04066992, 0.04647721],
                           [0.0088799 , 0.00977745, 0.01001304, 0.01110462, 0.01269174,
                            0.01429128, 0.01685596, 0.01935132, 0.0241224 , 0.02855202,
                            0.05491138, 0.06442595],
                           [0.00941056, 0.01082722, 0.01016549, 0.01132376, 0.01262646,
                            0.01484598, 0.01689528, 0.0199707 , 0.02385149, 0.03511326,
                            0.10805102, 0.25745362],
                           [0.00941056, 0.01082722, 0.01016549, 0.01132376, 0.01262646,
                            0.01484598, 0.01689528, 0.0199707 , 0.02385149, 0.03511326,
                            0.10805102, 0.25745362],
                           [0.0088799 , 0.00977745, 0.01001304, 0.01110462, 0.01269174,
                            0.01429128, 0.01685596, 0.01935132, 0.0241224 , 0.02855202,
                            0.05491138, 0.06442595],
                           [0.00750072, 0.00878589, 0.00942382, 0.0105949 , 0.01214719,
                            0.0138454 , 0.01611813, 0.01870347, 0.02401521, 0.02953272,
                            0.04066992, 0.04647721],
                           [0.00638303, 0.00779616, 0.00844854, 0.00977659, 0.01126267,
                            0.01248344, 0.01473596, 0.0174506 , 0.02122129, 0.02756312,
                            0.03485072, 0.0379259 ]])
    xT_rows, xT_cols = xT.shape
    x_bins = np.linspace(0, 100, xT_cols + 1)  # 12 bins for x-axis
    y_bins = np.linspace(0, 100, xT_rows + 1)  # 8 bins for y-axis
    df['x1_bin'] = pd.cut(df['x'], bins=x_bins, labels=False)
    df['y1_bin'] = pd.cut(df['y'], bins=y_bins, labels=False)
    df['x2_bin'] = pd.cut(df['end_x'], bins=x_bins, labels=False)
    df['y2_bin'] = pd.cut(df['end_y'], bins=y_bins, labels=False)
    passingthreat = df.loc[(df['typeId'] == 'Pass') & (df['outcome'] == 'Successful')]
    passingthreat = passingthreat.loc[passingthreat['x'] < 99.49]
    passingthreat = passingthreat.dropna(subset=['x1_bin', 'y1_bin', 'x2_bin', 'y2_bin'])
    passingthreat['x1_bin'] = passingthreat['x1_bin'].astype(int)
    passingthreat['y1_bin'] = passingthreat['y1_bin'].astype(int)
    passingthreat['x2_bin'] = passingthreat['x2_bin'].astype(int)
    passingthreat['y2_bin'] = passingthreat['y2_bin'].astype(int)
    passingthreat['xT_value'] = passingthreat.apply(
        lambda row: xT[row['y2_bin']][row['x2_bin']] - xT[row['y1_bin']][row['x1_bin']], 
        axis=1
    )
    passthreattotal = passingthreat.groupby('playerName')['xT_value'].sum().reset_index()
    carrythreat = df.loc[df['typeId'] == 'Carry']
    carrythreat['y_diff'] = carrythreat['y'] - carrythreat['end_y']
    carrythreat = carrythreat.dropna(subset=['x1_bin', 'y1_bin', 'x2_bin', 'y2_bin'])
    carrythreat['x1_bin'] = carrythreat['x1_bin'].astype(int)
    carrythreat['y1_bin'] = carrythreat['y1_bin'].astype(int)
    carrythreat['x2_bin'] = carrythreat['x2_bin'].astype(int)
    carrythreat['y2_bin'] = carrythreat['y2_bin'].astype(int)
    carrythreat['xT_value'] = carrythreat.apply(
        lambda row: xT[row['y2_bin']][row['x2_bin']] - xT[row['y1_bin']][row['x1_bin']], 
        axis=1
    )
    carrythreattotal = carrythreat.groupby('playerName')['xT_value'].sum().reset_index()
    df['id'] = df['id'].astype(str)
    passingthreat['id'] = passingthreat['id'].astype(str)
    df = df.merge(
        passingthreat[['id', 'xT_value']],
        on='id',
        how='left'
    )
    carrythreat['id'] = carrythreat['id'].astype(str)
    carrythreat['eventId'] = carrythreat['eventId'].astype(str)
    df['id'] = df['id'].astype(str)
    df['eventId'] = df['eventId'].astype(str)
    df = df.merge(
        carrythreat[['id', 'eventId', 'xT_value']],
        on=['id', 'eventId'],
        how='left',
        suffixes=('', '_carry')
    )
    df['xT_value'] = df['xT_value'].combine_first(df['xT_value_carry'])
    df.drop(columns=['xT_value_carry'], inplace=True)
    df['assist_xt'] = 0
    df.loc[df['keyPass'] == 1, 'assist_xt'] = 0.1
    df.loc[df['assist'] == 1, 'assist_xt'] = 0.6
    shotassisttotal = df.groupby('playerName', as_index=False)['assist_xt'].sum()
    shotassisttotal.rename(columns={'assist_xt': 'xT_value'}, inplace=True)
    shotassisttotal = shotassisttotal.loc[shotassisttotal['xT_value']>0]
    teamname = teamdata.iloc[0, 1]
    opponentname = teamdata.iloc[1,1]
    RPxT = np.array([[0.00638303, 0.00779616, 0.00844854, 0.00977659, 0.01126267,
                            0.01248344, 0.01473596, 0.0174506 , 0.02122129, 0.02756312,
                            0.03485072, 0.0379259 ],
                           [0.00750072, 0.00878589, 0.00942382, 0.0105949 , 0.01214719,
                            0.0138454 , 0.01611813, 0.01870347, 0.02401521, 0.02953272,
                            0.04066992, 0.04647721],
                           [0.0088799 , 0.00977745, 0.01001304, 0.01110462, 0.01269174,
                            0.01429128, 0.01685596, 0.01935132, 0.0241224 , 0.02855202,
                            0.05491138, 0.06442595],
                           [0.00941056, 0.01082722, 0.01016549, 0.01132376, 0.01262646,
                            0.01484598, 0.01689528, 0.0199707 , 0.02385149, 0.03511326,
                            0.10805102, 0.25745362],
                           [0.00941056, 0.01082722, 0.01016549, 0.01132376, 0.01262646,
                            0.01484598, 0.01689528, 0.0199707 , 0.02385149, 0.03511326,
                            0.10805102, 0.25745362],
                           [0.0088799 , 0.00977745, 0.01001304, 0.01110462, 0.01269174,
                            0.01429128, 0.01685596, 0.01935132, 0.0241224 , 0.02855202,
                            0.05491138, 0.06442595],
                           [0.00750072, 0.00878589, 0.00942382, 0.0105949 , 0.01214719,
                            0.0138454 , 0.01611813, 0.01870347, 0.02401521, 0.02953272,
                            0.04066992, 0.04647721],
                           [0.00638303, 0.00779616, 0.00844854, 0.00977659, 0.01126267,
                            0.01248344, 0.01473596, 0.0174506 , 0.02122129, 0.02756312,
                            0.03485072, 0.0379259 ]])
    RPxT_rows, RPxT_cols = RPxT.shape
    distinct_teams = df['team_name'].dropna().unique()
    teamsinmatch = teamdata[teamdata['name'].isin(distinct_teams)].copy()
    teamsinmatch.rename(columns={'name': 'team'}, inplace=True)
    teamsinmatch = teamsinmatch[['id', 'team']]
    teamname = teamsinmatch.iloc[0, 1]
    recthreattest = df.loc[df['team_name']==teamname]
    recthreattest = recthreattest.loc[recthreattest['end_x']>50]
    receivedpasshome = recthreattest[(recthreattest['typeId'] == 'Pass') & (recthreattest['outcome'] == 'Successful')]
    receivedpasshome['recipient'] = recthreattest['playerName'].shift(-1)
    receivedpasshome['x2_bin'] = pd.cut(receivedpasshome['end_x'], bins=RPxT_cols, labels=False)
    receivedpasshome['y2_bin'] = pd.cut(receivedpasshome['end_y'], bins=RPxT_rows, labels=False)
    receivedpasshome['xT_value'] = receivedpasshome[['x2_bin', 'y2_bin']].apply(lambda x: RPxT[x[1]][x[0]], axis=1)
    recpassh = receivedpasshome.groupby('recipient')['xT_value'].sum().reset_index()
    recpassh.rename(columns={'recipient': 'playerName'}, inplace=True)
    recthreattest = df.loc[df['team_name']!=teamname]
    recthreattest = recthreattest.loc[recthreattest['end_x']>50]
    receivedpassaway = recthreattest[(recthreattest['typeId'] == 'Pass') & (recthreattest['outcome'] == 'Successful')]
    receivedpassaway['recipient'] = recthreattest['playerName'].shift(-1)
    receivedpassaway['x2_bin'] = pd.cut(receivedpassaway['end_x'], bins=RPxT_cols, labels=False)
    receivedpassaway['y2_bin'] = pd.cut(receivedpassaway['end_y'], bins=RPxT_rows, labels=False)
    receivedpassaway['xT_value'] = receivedpassaway[['x2_bin', 'y2_bin']].apply(lambda x: RPxT[x[1]][x[0]], axis=1)
    recpassa = receivedpassaway.groupby('recipient')['xT_value'].sum().reset_index()
    recpassa.rename(columns={'recipient': 'playerName'}, inplace=True)
    recpassa
    receivedpasses = pd.concat([recpassh, recpassa], ignore_index=True)
    receivedpassestotal = receivedpasses.groupby('playerName')['xT_value'].sum().reset_index()
    RPxT = np.array([[0.00638303, 0.00779616, 0.00844854, 0.00977659, 0.01126267,
                            0.01248344, 0.01473596, 0.0174506 , 0.02122129, 0.02756312,
                            0.03485072, 0.0379259 ],
                           [0.00750072, 0.00878589, 0.00942382, 0.0105949 , 0.01214719,
                            0.0138454 , 0.01611813, 0.01870347, 0.02401521, 0.02953272,
                            0.04066992, 0.04647721],
                           [0.0088799 , 0.00977745, 0.01001304, 0.01110462, 0.01269174,
                            0.01429128, 0.01685596, 0.01935132, 0.0241224 , 0.02855202,
                            0.05491138, 0.06442595],
                           [0.00941056, 0.01082722, 0.01016549, 0.01132376, 0.01262646,
                            0.01484598, 0.01689528, 0.0199707 , 0.02385149, 0.03511326,
                            0.10805102, 0.25745362],
                           [0.00941056, 0.01082722, 0.01016549, 0.01132376, 0.01262646,
                            0.01484598, 0.01689528, 0.0199707 , 0.02385149, 0.03511326,
                            0.10805102, 0.25745362],
                           [0.0088799 , 0.00977745, 0.01001304, 0.01110462, 0.01269174,
                            0.01429128, 0.01685596, 0.01935132, 0.0241224 , 0.02855202,
                            0.05491138, 0.06442595],
                           [0.00750072, 0.00878589, 0.00942382, 0.0105949 , 0.01214719,
                            0.0138454 , 0.01611813, 0.01870347, 0.02401521, 0.02953272,
                            0.04066992, 0.04647721],
                           [0.00638303, 0.00779616, 0.00844854, 0.00977659, 0.01126267,
                            0.01248344, 0.01473596, 0.0174506 , 0.02122129, 0.02756312,
                            0.03485072, 0.0379259 ]])
    RPxT_rows, RPxT_cols = RPxT.shape
    recthreattest = df.loc[df['team_name']==teamname]
    recthreattest = recthreattest.loc[recthreattest['end_x']>50]
    receivedpasshome = recthreattest[(recthreattest['typeId'] == 'Pass') & (recthreattest['outcome'] == 'Successful')]
    receivedpasshome['x2_bin'] = pd.cut(receivedpasshome['end_x'], bins=RPxT_cols, labels=False)
    receivedpasshome['y2_bin'] = pd.cut(receivedpasshome['end_y'], bins=RPxT_rows, labels=False)
    receivedpasshome['xT_value'] = receivedpasshome[['x2_bin', 'y2_bin']].apply(lambda x: RPxT[x[1]][x[0]], axis=1)
    recpassh = receivedpasshome.groupby('pass_recipient')['xT_value'].sum().reset_index()
    recpassh.rename(columns={'pass_recipient': 'playerName'}, inplace=True)
    recthreattest = df.loc[df['team_name']!=teamname]
    recthreattest = recthreattest.loc[recthreattest['end_x']>50]
    receivedpassaway = recthreattest[(recthreattest['typeId'] == 'Pass') & (recthreattest['outcome'] == 'Successful')]
    receivedpassaway['x2_bin'] = pd.cut(receivedpassaway['end_x'], bins=RPxT_cols, labels=False)
    receivedpassaway['y2_bin'] = pd.cut(receivedpassaway['end_y'], bins=RPxT_rows, labels=False)
    receivedpassaway['xT_value'] = receivedpassaway[['x2_bin', 'y2_bin']].apply(lambda x: RPxT[x[1]][x[0]], axis=1)
    recpassa = receivedpassaway.groupby('pass_recipient')['xT_value'].sum().reset_index()
    recpassa.rename(columns={'pass_recipient': 'playerName'}, inplace=True)
    recpassa
    receivedpasses = pd.concat([recpassh, recpassa], ignore_index=True)
    receivedpassestotal = receivedpasses.groupby('playerName')['xT_value'].sum().reset_index()
    eventstoinclude = ['Tackle',
                       'Aerial',
                       'Challenge',
                       'Interception',
                       'Blocked Pass',
                       'Clearance',
                       'Ball recovery'
                      ]
    df_events_def = df[df['typeId'].isin(eventstoinclude)]
    xT = np.array([[0.00638303, 0.00779616, 0.00844854, 0.00977659, 0.01126267,
                            0.01248344, 0.01473596, 0.0174506 , 0.02122129, 0.02756312,
                            0.03485072, 0.0379259 ],
                           [0.00750072, 0.00878589, 0.00942382, 0.0105949 , 0.01214719,
                            0.0138454 , 0.01611813, 0.01870347, 0.02401521, 0.02953272,
                            0.04066992, 0.04647721],
                           [0.0088799 , 0.00977745, 0.01001304, 0.01110462, 0.01269174,
                            0.01429128, 0.01685596, 0.01935132, 0.0241224 , 0.02855202,
                            0.05491138, 0.06442595],
                           [0.00941056, 0.01082722, 0.01016549, 0.01132376, 0.01262646,
                            0.01484598, 0.01689528, 0.0199707 , 0.02385149, 0.03511326,
                            0.10805102, 0.25745362],
                           [0.00941056, 0.01082722, 0.01016549, 0.01132376, 0.01262646,
                            0.01484598, 0.01689528, 0.0199707 , 0.02385149, 0.03511326,
                            0.10805102, 0.25745362],
                           [0.0088799 , 0.00977745, 0.01001304, 0.01110462, 0.01269174,
                            0.01429128, 0.01685596, 0.01935132, 0.0241224 , 0.02855202,
                            0.05491138, 0.06442595],
                           [0.00750072, 0.00878589, 0.00942382, 0.0105949 , 0.01214719,
                            0.0138454 , 0.01611813, 0.01870347, 0.02401521, 0.02953272,
                            0.04066992, 0.04647721],
                           [0.00638303, 0.00779616, 0.00844854, 0.00977659, 0.01126267,
                            0.01248344, 0.01473596, 0.0174506 , 0.02122129, 0.02756312,
                            0.03485072, 0.0379259 ]])
    xT_rows, xT_cols = xT.shape
    df_events_def['x'] = 105 - df_events_def['x']
    df_events_def['end_x'] = 105 - df_events_def['end_x']
    df_events_def['x1_bin'] = pd.cut(df_events_def['x'], bins=xT_cols, labels=False)
    df_events_def['y1_bin'] = pd.cut(df_events_def['y'], bins=xT_rows, labels=False)
    df_events_def['xT_value'] = df_events_def[['x1_bin', 'y1_bin']].apply(lambda x: xT[x[1]][x[0]], axis=1)
    df_events_def['xT_value'] = df_events_def.apply(lambda row: row['xT_value'] * -1 if row['outcome'] == 'Unsuccessful' else row['xT_value'], axis=1)
    defthreattotal = df_events_def.groupby('playerName')['xT_value'].sum().reset_index()
    df = df.merge(
        df_events_def[['id', 'xT_value']],
        on='id',
        how='left',
        suffixes=('', '_carry')
    )
    df['xT_value'] = df['xT_value'].combine_first(df['xT_value_carry'])
    df.drop(columns=['xT_value_carry'], inplace=True)
    IPxT = np.array([[0.01, 0.012, 0.013, 0.015, 0.017,
                    0.018, 0.02, 0.022 , 0.025, 0.02756312,
                    0.03485072, 0.0379259 ],
                   [0.012, 0.01378589, 0.01442382, 0.0155949 , 0.01714719,
                    0.0188454 , 0.02111813, 0.02370347, 0.02701521, 0.02953272,
                    0.04066992, 0.04647721],
                   [0.01388799 , 0.01477745, 0.01501304, 0.01610462, 0.01869174,
                    0.020, 0.02285596, 0.02535132, 0.031224 , 0.0455202,
                    0.05491138, 0.06442595],
                   [0.02941056, 0.03082722, 0.03216549, 0.03432376, 0.0462646,
                    0.04784598, 0.0589528, 0.0699707 , 0.07385149, 0.08511326,
                    0.10805102, 0.25745362],
                   [0.02941056, 0.03082722, 0.03216549, 0.03432376, 0.0462646,
                    0.04784598, 0.0589528, 0.0699707 , 0.07385149, 0.08511326,
                    0.10805102, 0.25745362],
                   [0.01388799 , 0.01477745, 0.01501304, 0.01610462, 0.01869174,
                    0.020, 0.02285596, 0.02535132, 0.031224 , 0.0455202,
                    0.05491138, 0.06442595],
                   [0.012, 0.01378589, 0.01442382, 0.0155949 , 0.01714719,
                    0.0188454 , 0.02111813, 0.02370347, 0.02701521, 0.02953272,
                    0.04066992, 0.04647721],
                   [0.01, 0.012, 0.013, 0.015, 0.017,
                    0.018, 0.02, 0.022 , 0.025, 0.02756312,
                    0.03485072, 0.0379259 ]])
    IPxT_rows, IPxT_cols = IPxT.shape
    incompletepasses = df.loc[(df['typeId'] == 'Pass') & (df['outcome'] == 'Unsuccessful')]
    incompletepasses['x'] = 105 - incompletepasses['x']
    incompletepasses['end_x'] = 105 - incompletepasses['end_x']
    incompletepasses['x1_bin'] = pd.cut(incompletepasses['x'], bins=IPxT_cols, labels=False)
    incompletepasses['y1_bin'] = pd.cut(incompletepasses['y'], bins=IPxT_rows, labels=False)
    incompletepasses['xT_value'] = incompletepasses[['x1_bin', 'y1_bin']].apply(lambda x: IPxT[x[1]][x[0]], axis=1)
    incompletepasses['xT_value'] = incompletepasses['xT_value']*-1
    incomppasstotal = incompletepasses.groupby('playerName')['xT_value'].sum().reset_index()
    df = df.merge(
        incompletepasses[['id', 'xT_value']],
        on='id',
        how='left',
        suffixes=('', '_carry')
    )
    df['xT_value'] = df['xT_value'].combine_first(df['xT_value_carry'])
    df.drop(columns=['xT_value_carry'], inplace=True)
    df['card_value'] = 0
    df.loc[df['yellowcard'] == 1, 'card_value'] = -0.275
    df.loc[df['yellowcard2'] == 1, 'card_value'] = -0.525
    df.loc[df['redcard'] == 1, 'card_value'] = -0.8
    cards_df = df.groupby('playerName', as_index=False)['card_value'].sum()
    cards_df = cards_df.rename(columns={'card_value': 'xT_value'})

    #### SHOTS

    shotstaken = df[df['typeId'].isin(['Miss', 'Goal', 'Attempt Saved'])]

    # Optionally reset the index
    shotstaken = shotstaken.reset_index(drop=True)
    # Make sure shotstaken DataFrame already exists as per your previous step

    # Add a new column 'xT_value' with default NaN (optional)
    # Make sure shotstaken DataFrame already exists as per your previous step

    # Add a new column 'xT_value' with default NaN (optional)
    shotstaken['xT_value'] = None

    # Assign values based on typeId
    shotstaken.loc[shotstaken['typeId'] == 'Goal', 'xT_value'] = 0.95
    shotstaken.loc[shotstaken['typeId'] == 'Attempt Saved', 'xT_value'] = 0.2
    shotstaken.loc[shotstaken['typeId'] == 'Miss', 'xT_value'] = 0.05
    shotstaken.loc[shotstaken['shotblocked'] == 1, 'xT_value'] = 0.05

    # Optionally convert xT_value to float type
    shotstaken['xT_value'] = shotstaken['xT_value'].astype(float)

    shotstakentotal = shotstaken.groupby('playerName')['xT_value'].sum().reset_index()
    df = df.merge(
        shotstaken[['id', 'xT_value']],
        on='id',
        how='left',
        suffixes=('', '_carry')
    )
    df['xT_value'] = df['xT_value'].combine_first(df['xT_value_carry'])
    df.drop(columns=['xT_value_carry'], inplace=True)

    ##GOALS CONCEDED
    starting_lineups = starting_lineups.merge(teamdata, left_on='contestant_id', right_on='id', how='left')
    starting_lineups.rename(columns={'name': 'team_name'}, inplace=True)

    # Ensure numeric columns for time comparisons
    starting_lineups['time_on'] = pd.to_numeric(starting_lineups['time_on'])
    starting_lineups['time_off'] = pd.to_numeric(starting_lineups['time_off'])

    shootout_scores = calculate_shootout_scores(df)
    regulation_mask = regulation_period_mask(df['periodId'])

    # Step 1: Add goal event info from regulation and extra-time periods only
    goal_events = df[
        regulation_mask & df['typeId'].isin(['Goal', 'Own Goal'])
    ].copy()
    goal_events['minute'] = pd.to_numeric(goal_events['timeMin'], errors='coerce')

    # Step 2: Identify the two team names in the match
    team_names = df['team_name'].dropna().unique()

    # Step 3: Assign team_goal column
    goal_events['team_goal'] = goal_events.apply(
        lambda row: row['team_name'] if row['typeId'] == 'Goal'
        else (
            [team for team in team_names if team != row['team_name']][0]
            if row['typeId'] == 'Own Goal' else None
        ),
        axis=1
    )

    # Step 4: Calculate goals scored/conceded per player
    def get_goals_for_and_against(player_row):
        time_on = player_row['time_on']
        time_off = player_row['time_off']
        player_team = player_row['team_name']
        
        active_goals = goal_events[
            (goal_events['minute'] >= time_on) &
            (goal_events['minute'] <= time_off)
        ]
        
        goals_for = (active_goals['team_goal'] == player_team).sum()
        goals_against = (active_goals['team_goal'] != player_team).sum()
        
        return pd.Series({'goals_scored': goals_for, 'goals_conceded': goals_against})

    # Apply the goal calculations to starting_lineups
    starting_lineups[['goals_scored', 'goals_conceded']] = starting_lineups.apply(get_goals_for_and_against, axis=1)
    def calculate_xt_value(row):
        pos = row['position']
        mins = row['minutes_played']
        goals_conceded = row['goals_conceded']
        if any(p in pos for p in ['LB', 'CB', 'RB', 'RWB', 'LWB']):
            if mins > 60 and goals_conceded == 0:
                return 0.4
            else:
                return goals_conceded * -0.2
        elif 'M' in pos:
            if mins > 60 and goals_conceded == 0:
                return 0.1
            else:
                return goals_conceded * -0.05
        return 0  # or you can set to None if not applicable





    goal_conceded_rows = []

    # Create player lookup maps
    player_name_map = starting_lineups.set_index('player_id')['player_name'].to_dict()
    team_name_map = starting_lineups.set_index('player_id')['team_name'].to_dict()

    # Get the two teams in the match
    team_names = df['team_name'].dropna().unique()

    # Identify the team that conceded each goal
    goal_events = goal_events.copy()
    goal_events['conceding_team'] = goal_events.apply(
        lambda row: (
            [team for team in team_names if team != row['team_name']][0]
            if row['typeId'] == 'Goal'
            else row['team_name']  # for Own Goal, the team credited with the own goal conceded it
        ),
        axis=1
    )

    # Iterate through each goal
    for _, goal_row in goal_events.iterrows():
        conceded_team = goal_row['conceding_team']
        goal_minute = goal_row['timeMin']
        goal_sec = goal_row['timeSec']
        goal_period = goal_row['periodId']

        # Get all players from the conceding team who were on the pitch at the time
        active_players = starting_lineups[
            (starting_lineups['team_name'] == conceded_team) &
            (starting_lineups['time_on'] <= goal_minute) &
            (starting_lineups['time_off'] >= goal_minute)
        ]

        for _, player in active_players.iterrows():
            pid = player['player_id']
            player_name = player['player_name']
            team_name = player['team_name']

            # Get most recent position using the resolve_position function
            playing_pos = resolve_position({
                'playerId': pid,
                'periodId': goal_period,
                'timeMin': goal_minute,
                'timeSec': goal_sec
            })

            # Fallback if position is not found
            if pd.isna(playing_pos) or not playing_pos:
                xt_val = 0
            else:
                if any(p in playing_pos for p in ['LB', 'CB', 'RB', 'RWB', 'LWB']):
                    xt_val = -0.2
                elif 'M' in playing_pos:
                    xt_val = -0.05
                else:
                    xt_val = 0

            goal_conceded_rows.append({
                'playerName': player_name,
                'team_name': team_name,
                'timeMin': goal_minute,
                'timeSec': goal_sec,
                'periodId': goal_period,
                'playing_position': playing_pos,
                'typeId': 'goal_conceded',
                'xT_value': xt_val
            })

    # Convert and deduplicate
    goal_conceded_df = pd.DataFrame(goal_conceded_rows)
    goal_conceded_df = goal_conceded_df.drop_duplicates(
        subset=['periodId', 'timeMin', 'timeSec', 'playerName', 'team_name']
    )

    # Ensure all columns match df
    for col in df.columns:
        if col not in goal_conceded_df.columns:
            goal_conceded_df[col] = None

    # Append to main df
    df = pd.concat([df, goal_conceded_df], ignore_index=True)
    df = df.sort_values(by=['periodId', 'timeMin', 'timeSec']).reset_index(drop=True)

    # =========================
    # CLEAN SHEET LOGIC BELOW
    # =========================

    # Get teams that actually conceded (from corrected logic)
    teams_conceded = goal_events['conceding_team'].unique()

    # Only allow clean sheets for players on teams that did NOT concede
    clean_sheet_eligible = starting_lineups[
        (starting_lineups['minutes_played'] > 60) &
        (starting_lineups['goals_conceded'] == 0) &
        (~starting_lineups['team_name'].isin(teams_conceded))
    ]

    clean_sheet_rows = []

    for _, player in clean_sheet_eligible.iterrows():
        pos = player['position']
        if pd.isna(pos):
            continue

        if any(p in pos for p in ['LB', 'CB', 'RB', 'RWB', 'LWB']):
            xt_val = 0.4
        elif 'M' in pos:
            xt_val = 0.1
        else:
            xt_val = None

        clean_sheet_rows.append({
            'playerName': player['player_name'],
            'team_name': player['team_name'],
            'typeId': 'clean_sheet',
            'playing_position': pos,
            'xT_value': xt_val
        })

    clean_sheet_df = pd.DataFrame(clean_sheet_rows)

    # Ensure all columns match df
    for col in df.columns:
        if col not in clean_sheet_df.columns:
            clean_sheet_df[col] = None

    # Append and sort
    df = pd.concat([df, clean_sheet_df], ignore_index=True)
    df = df.sort_values(by=['periodId', 'timeMin', 'timeSec'], na_position='last').reset_index(drop=True)


    clean_sheet_mask = df['typeId'] == 'clean_sheet'
    df = pd.concat([
        df[~clean_sheet_mask],
        df[clean_sheet_mask].drop_duplicates(subset=['playerName', 'playing_position'])
    ]).reset_index(drop=True)

    starting_lineups = starting_lineups[starting_lineups['minutes_played'].notna()]

    starting_lineups['xT_value'] = starting_lineups.apply(calculate_xt_value, axis=1)
    starting_lineups['periodId'] = (
        starting_lineups['periodId_x']
        .combine_first(starting_lineups['periodId_y'])
    )
    goalsconcededtotal = df[df['typeId'].isin(['goal_conceded', 'clean_sheet'])][['playerName', 'xT_value']].copy()
    goalsconcededtotal = goalsconcededtotal.groupby('playerName', as_index=False)['xT_value'].sum()
    ##TAKE ON
    takeondf = df[df['typeId'] == 'Take On'].copy()
    takeondf['x'] = pd.to_numeric(takeondf['x'], errors='coerce')
    def assign_xt(row):
        if row['x'] < 33.33:
            return -0.15 if row['outcome'] == 'Unsuccessful' else 0.05
        elif row['x'] < 66.66:
            return -0.1 if row['outcome'] == 'Unsuccessful' else 0.1
        else:
            return -0.05 if row['outcome'] == 'Unsuccessful' else 0.15
    takeondf['xT_value'] = takeondf.apply(assign_xt, axis=1)
    takeontotal = takeondf.groupby('playerName')['xT_value'].sum().reset_index()
    df = df.merge(
        takeondf[['id', 'xT_value']],
        on='id',
        how='left',
        suffixes=('', '_carry')
    )
    df['xT_value'] = df['xT_value'].combine_first(df['xT_value_carry'])
    df.drop(columns=['xT_value_carry'], inplace=True)
    #ERRORS
    errorsdf = df[(df['errorshot'] == 1) | (df['errorgoal'] == 1)].copy()
    def assign_error_xt(row):
        if row.get('errorgoal') == 1:
            return -0.5
        elif row.get('errorshot') == 1:
            return -0.1
        return 0  # fallback (shouldn't occur with current filter)
    errorsdf['xT_value'] = errorsdf.apply(assign_error_xt, axis=1)
    errorstotal = errorsdf.groupby('playerName')['xT_value'].sum().reset_index()
    df = df.merge(
        errorsdf[['id', 'xT_value']],
        on='id',
        how='left',
        suffixes=('', '_carry')
    )
    df['xT_value'] = df['xT_value'].combine_first(df['xT_value_carry'])
    df.drop(columns=['xT_value_carry'], inplace=True)
    #DISPOSSESSED
    dispossdf = df[df['typeId'] == 'Dispossessed'].copy()
    def assign_disposs_xt(x):
        if x < 33.3:
            return -0.15
        elif 33.3 <= x < 66.6:
            return -0.01
        else:  # x >= 66.6
            return -0.05
    dispossdf['xT_value'] = dispossdf['x'].apply(assign_disposs_xt)
    disposstotal = dispossdf.groupby('playerName')['xT_value'].sum().reset_index()
    df = df.merge(
        errorsdf[['id', 'xT_value']],
        on='id',
        how='left',
        suffixes=('', '_carry')
    )
    df['xT_value'] = df['xT_value'].combine_first(df['xT_value_carry'])
    df.drop(columns=['xT_value_carry'], inplace=True)
    dataframes = [
        shotstakentotal,
        defthreattotal,
        incomppasstotal,
        passthreattotal,
        carrythreattotal,
        cards_df,
        shotassisttotal,
        receivedpassestotal,
        goalsconcededtotal,
        takeontotal,
        errorstotal,
        disposstotal
    #    keepertotals
    ]
    valid_dataframes = [df for df in dataframes if isinstance(df, pd.DataFrame) and not df.empty]


    totalxt = pd.concat(dataframes)
    totalxt = totalxt.groupby('playerName', as_index=False).sum()
    totalxt = totalxt.sort_values(by='xT_value', ascending=False)
    goalkeepers = starting_lineups[starting_lineups['position'] == 'GK']['player_name'].unique()
    totalxt = totalxt[~totalxt['playerName'].isin(goalkeepers)].reset_index(drop=True)
    trimmed_xt = totalxt.iloc[1:-1]
    mean_xt = trimmed_xt['xT_value'].mean()
    totalxt['Player Impact'] = totalxt['xT_value'] - mean_xt
    totalxt['Player Impact'] = totalxt['Player Impact'].round(2)
    totalxt['Player Impact'] = totalxt['Player Impact'].apply(
        lambda x: f"+{x:.2f}" if x > 0 else f"-{abs(x):.2f}"
    )
    totalxt['Match Rank'] = totalxt['xT_value'].rank(method='max', ascending=False)
    totalxt['Match Rank'] = totalxt['Match Rank'].astype(int)
    totalxt.rename(columns={'xT_value': 'Threat Value'}, inplace=True)
    starting_lineups = starting_lineups.merge(
        totalxt,
        how='left',
        left_on='player_name',
        right_on='playerName'
    )
    starting_lineups = starting_lineups.drop_duplicates(subset=['player_id', 'match_id'], keep='first')
    for col in df.columns:
        if col not in position_change_df.columns:
            position_change_df[col] = None
    df = pd.concat([df, position_change_df], ignore_index=True)
            # Calculate distance to goal for all rows
    df['start_distance'] = ((df['x'] - 100) ** 2 + (df['y'] - 50) ** 2) ** 0.5
    df['end_distance'] = ((df['end_x'] - 100) ** 2 + (df['end_y'] - 50) ** 2) ** 0.5

            # -------- Progressive Carry Logic --------
            # Progressive if Carry and at least 20% closer to goal
    df['progressive_carry'] = 'No'
    carry_mask = (df['typeId'] == 'Carry') & (df['end_distance'] < 0.8 * df['start_distance'])
    df.loc[carry_mask, 'progressive_carry'] = 'Yes'

            # -------- Progressive Pass Logic --------
            # Define pass zones and thresholds
    pass_conditions = [
        (df['x'] <= 50) & (df['end_x'] <= 50),      # Defensive third
        (df['x'] <= 50) & (df['end_x'] >= 50),      # From defensive to middle
        (df['x'] > 50) & (df['x'] <= 75),           # Middle third
        (df['x'] > 75)                                        # Final third
        ]
    pass_percentages = [0.65, 0.80, 0.85, 1.00]

            # Initialize column
    df['progressive_pass'] = 'No'

            # Apply conditions only to Successful Passes
    is_pass = (df['typeId'] == 'Pass') & (df['outcome'] == 'Successful')
    for cond, threshold in zip(pass_conditions, pass_percentages):
        pass_mask = is_pass & cond & (df['end_distance'] < threshold * df['start_distance'])
        df.loc[pass_mask, 'progressive_pass'] = 'Yes'
    df['assist'] = pd.to_numeric(df['assist'], errors='coerce').fillna(0)
    df['keyPass'] = pd.to_numeric(df['keyPass'], errors='coerce').fillna(0)
    df['xT_value'] = pd.to_numeric(df['xT_value'], errors='coerce').fillna(0)

    df.loc[df['keyPass'] == 1, 'xT_value'] = df.loc[df['keyPass'] == 1, 'xT_value'] + 0.1
    df.loc[df['assist'] == 1, 'xT_value'] = 0.6







    #### NEW GOALKEEPER STUFF

    def to_abs_min(period_id, time_min, time_sec=0):
        if pd.isna(time_min):
            return pd.NA
        period_id = int(period_id) if pd.notna(period_id) else 1
        t = float(time_min) + (float(time_sec) / 60.0 if pd.notna(time_sec) else 0.0)

        if period_id == 1:
            return t
        if period_id == 2:
            return t if t > 45 else (45.0 + t)
        if period_id == 3:
            return t if t > 90 else (90.0 + t)
        if period_id == 4:
            return t if t > 105 else (105.0 + t)
        return t
    if 'abs_min' not in df.columns:
        df['abs_min'] = df.apply(lambda r: to_abs_min(r.get('periodId'), r.get('timeMin'), r.get('timeSec', 0)), axis=1)

    match_end_abs = pd.to_numeric(df['abs_min'], errors='coerce').max()

    starting_lineups = starting_lineups.copy()

    # Make sure these exist / are numeric
    starting_lineups['time_on']  = pd.to_numeric(starting_lineups.get('time_on'),  errors='coerce')
    starting_lineups['time_off'] = pd.to_numeric(starting_lineups.get('time_off'), errors='coerce')

    # We will use ONE periodId column for the player's time window.
    # If you still have periodId_x/periodId_y, prefer "periodId" if present,
    # else take periodId_y (sub-on) else periodId_x (sub-off) else 1.
    if 'periodId' not in starting_lineups.columns:
        starting_lineups['periodId'] = np.nan

    if 'periodId_y' in starting_lineups.columns:
        starting_lineups['periodId'] = starting_lineups['periodId'].combine_first(starting_lineups['periodId_y'])
    if 'periodId_x' in starting_lineups.columns:
        starting_lineups['periodId'] = starting_lineups['periodId'].combine_first(starting_lineups['periodId_x'])

    starting_lineups['periodId'] = pd.to_numeric(starting_lineups['periodId'], errors='coerce').fillna(1).astype(int)

    # time_on_abs:
    # - starters => 0
    # - subs => convert (periodId, time_on)
    starting_lineups['time_on_abs'] = np.where(
        starting_lineups['is_starter'].astype(str).str.lower().eq('yes'),
        0.0,
        starting_lineups.apply(lambda r: to_abs_min(r['periodId'], r['time_on'], 0), axis=1)
    )

    # time_off_abs:
    # - if time_off missing, fall back to match end
    # - convert (periodId, time_off) to absolute timeline (works for both absolute and period-relative providers)
    starting_lineups['time_off_abs'] = starting_lineups.apply(
        lambda r: to_abs_min(r['periodId'], r['time_off'], 0) if pd.notna(r['time_off']) else match_end_abs,
        axis=1
    )

    # If anything still missing, hard fallback
    starting_lineups['time_on_abs']  = pd.to_numeric(starting_lineups['time_on_abs'],  errors='coerce').fillna(0.0)
    starting_lineups['time_off_abs'] = pd.to_numeric(starting_lineups['time_off_abs'], errors='coerce').fillna(match_end_abs)

    sl = starting_lineups.copy()

    # Normalize yes/no
    for c in ['is_starter', 'subbed_on', 'subbed_off']:
        if c in sl.columns:
            sl[c] = sl[c].astype(str).str.lower()

    # Ensure numeric
    sl['time_on']  = pd.to_numeric(sl['time_on'], errors='coerce').fillna(0)
    sl['time_off'] = pd.to_numeric(sl['time_off'], errors='coerce')

    # If time_off missing, fall back to minutes_played (or match end later)
    sl['minutes_played'] = pd.to_numeric(sl.get('minutes_played'), errors='coerce')
    sl['time_off'] = sl['time_off'].combine_first(sl['minutes_played'])

    # Infer period-of-entry:
    # - starters: period 1
    # - subs: use periodId_y if present else 2
    sl['on_periodId'] = 1
    if 'periodId_y' in sl.columns:
        sl.loc[sl['subbed_on'].eq('yes'), 'on_periodId'] = pd.to_numeric(sl.loc[sl['subbed_on'].eq('yes'), 'periodId_y'],
                                                                           errors='coerce').fillna(2).astype(int)
    else:
        sl.loc[sl['subbed_on'].eq('yes'), 'on_periodId'] = 2

    # Infer period-of-exit:
    # - if subbed_off: use periodId_x if present else use on_periodId
    # - otherwise assume they can cover through later periods (we’ll handle selection by period anyway)
    sl['off_periodId'] = sl['on_periodId']
    if 'periodId_x' in sl.columns:
        mask_off = sl['subbed_off'].eq('yes')
        sl.loc[mask_off, 'off_periodId'] = pd.to_numeric(sl.loc[mask_off, 'periodId_x'],
                                                         errors='coerce').fillna(sl.loc[mask_off, 'on_periodId']).astype(int)

    # Now identify the GK *role*.
    # IMPORTANT: you said Gunn is listed as LW but actually plays GK later.
    # So we treat a player as a GK candidate if ANY of these hold:
    # - position == 'GK'
    # - any position{i} == 'GK'
    pos_cols = [c for c in sl.columns if c.startswith('position') and not c.endswith('mins')]
    def row_has_gk(r):
        if str(r.get('position', '')).strip() == 'GK':
            return True
        for c in pos_cols:
            if str(r.get(c, '')).strip() == 'GK':
                return True
        return False

    sl['is_gk_candidate'] = sl.apply(row_has_gk, axis=1)
    gk_candidates = sl[sl['is_gk_candidate']].copy()

    # Build per-team per-period preferred GK:
    # Rule:
    # - period 1: prefer starter GK (is_starter == yes)
    # - period >=2: prefer a player who has GK role and is "subbed_on == yes" in that period,
    #               otherwise fall back to starter GK.
    gk_by_team_period = {}

    for team, grp in gk_candidates.groupby('team_name'):
        team_map = {}

        # Starter GK (for period 1 fallback)
        starter = grp[(grp['is_starter'] == 'yes') & ((grp['position'].astype(str).str.strip() == 'GK') | (grp.apply(row_has_gk, axis=1)))]
        starter_name = starter.iloc[0]['player_name'] if not starter.empty else None

        # Period 1
        team_map[1] = starter_name

        # Period 2+ : look for GK candidate subbed on in that period (e.g. Gunn)
        for p in [2, 3, 4]:
            p_sub = grp[(grp['subbed_on'] == 'yes') & (grp['on_periodId'] == p)]
            if not p_sub.empty:
                # If multiple, choose earliest time_on
                p_sub = p_sub.sort_values('time_on')
                team_map[p] = p_sub.iloc[0]['player_name']
            else:
                team_map[p] = starter_name

        gk_by_team_period[team] = team_map


    # -----------------------------
    # 2) Opponent team helper
    # -----------------------------
    match_teams = [t for t in df['team_name'].dropna().unique()]

    def get_opponent_team(team):
        if team in match_teams and len(match_teams) == 2:
            return match_teams[0] if match_teams[1] == team else match_teams[1]
        return None


    # -----------------------------
    # 3) Resolve GK faced by shot using SHOT periodId (critical)
    # -----------------------------
    def resolve_opposition_gk_period_aware(row):
        shooting_team = row.get('team_name')
        if pd.isna(shooting_team):
            return None

        opp_team = get_opponent_team(shooting_team)
        if opp_team is None:
            return None

        p = row.get('periodId')
        if pd.isna(p):
            return None
        p = int(p)

        return gk_by_team_period.get(opp_team, {}).get(p, None)


    # -----------------------------
    # 4) Apply to shot-like events
    # -----------------------------
    shot_types = ['Goal', 'Miss', 'Attempt Saved', 'Post']

    # Make sure cross is numeric-ish (handles strings/NaN safely)
    df['cross'] = pd.to_numeric(df.get('cross', 0), errors='coerce').fillna(0).astype(int)
    df.loc[(df['cross'] == 1) & (df['typeId'] != 'Pass'), 'cross'] = 0

    # Create one mask that covers both cases
    shot_mask = df['typeId'].isin(shot_types)
    cross_mask = df['cross'].eq(1)

    target_mask = shot_mask | cross_mask

    # Only resolve GK for relevant events
    df['playing_GK'] = None
    df.loc[target_mask, 'playing_GK'] = df.loc[target_mask].apply(resolve_opposition_gk_period_aware, axis=1)
    SIX_X_MIN, SIX_X_MAX = 94.2, 100.0
    SIX_Y_MIN, SIX_Y_MAX = 36.8, 63.2


    def _point_in_rect(px, py, xmin, xmax, ymin, ymax):
        return (xmin <= px <= xmax) and (ymin <= py <= ymax)


    def _segment_intersects_rect(x1, y1, x2, y2, xmin, xmax, ymin, ymax):
        """
        Returns True if the line segment (x1,y1)->(x2,y2) intersects the axis-aligned rectangle.
        Uses Liang–Barsky line clipping (robust for segment-rectangle intersection).
        """
        # If either endpoint is inside, it's an intersection
        if _point_in_rect(x1, y1, xmin, xmax, ymin, ymax) or _point_in_rect(x2, y2, xmin, xmax, ymin, ymax):
            return True

        dx = x2 - x1
        dy = y2 - y1

        p = [-dx, dx, -dy, dy]
        q = [x1 - xmin, xmax - x1, y1 - ymin, ymax - y1]

        u1, u2 = 0.0, 1.0

        for pi, qi in zip(p, q):
            if pi == 0:
                # Segment is parallel to this boundary; if outside, no intersection
                if qi < 0:
                    return False
            else:
                t = qi / pi
                if pi < 0:
                    if t > u2:
                        return False
                    if t > u1:
                        u1 = t
                else:
                    if t < u1:
                        return False
                    if t < u2:
                        u2 = t

        return u1 <= u2


    # ----------------------------
    # Create cross_into_six = "yes"/"no"
    # ----------------------------
    # Ensure coords are numeric
    for c in ['x', 'y', 'end_x', 'end_y']:
        df[c] = pd.to_numeric(df[c], errors='coerce')

    # Ensure cross flag is numeric 0/1
    df['cross'] = pd.to_numeric(df.get('cross', 0), errors='coerce').fillna(0).astype(int)

    def cross_into_six_row(r):
        # Only crosses count
        if r.get('cross', 0) != 1:
            return "no"

        x1, y1, x2, y2 = r['x'], r['y'], r['end_x'], r['end_y']
        if pd.isna(x1) or pd.isna(y1) or pd.isna(x2) or pd.isna(y2):
            return "no"

        hit = _segment_intersects_rect(
            float(x1), float(y1), float(x2), float(y2),
            SIX_X_MIN, SIX_X_MAX, SIX_Y_MIN, SIX_Y_MAX
        )
        return "yes" if hit else "no"

    df['cross_into_six'] = df.apply(cross_into_six_row, axis=1)

    # ----------------------------
    # Player event counts (periods 1-4)
    # ----------------------------
    count_columns = [
        'Goals',
        'Assists',
        'Key Passes',
        'Dribbles',
        'Ball Recoveries',
        'Clearance',
        'Interceptions',
        'Tackles',
        'Blocks/Saves',
        'Shots on Target',
        'Yellow Card',
        'Red Card',
        'Own Goal',
        'Penalty Scored',
        'Penalty Missed',
        'Penalty Saved'
    ]

    event_counts = df[regulation_period_mask(df['periodId'])].copy()
    event_counts = event_counts[event_counts['playerName'].notna()].copy()
    event_counts['playerName'] = event_counts['playerName'].astype(str).str.strip()

    for col in ['assist', 'keyPass', 'yellowcard', 'yellowcard2', 'redcard', 'penalty']:
        if col not in event_counts.columns:
            event_counts[col] = 0
        else:
            event_counts[col] = pd.to_numeric(event_counts[col], errors='coerce').fillna(0)

    if 'next_position' not in event_counts.columns:
        event_counts['next_position'] = None

    is_not_carry = event_counts['typeId'].ne('Carry')
    is_attempt_saved = event_counts['typeId'].isin(['Attempted Saved', 'Attempt Saved'])

    event_counts['Goals'] = event_counts['typeId'].eq('Goal').astype(int)
    event_counts['Assists'] = (is_not_carry & event_counts['assist'].eq(1)).astype(int)
    event_counts['Key Passes'] = (
        is_not_carry &
        (event_counts['assist'].eq(1) | event_counts['keyPass'].eq(1))
    ).astype(int)
    event_counts['Dribbles'] = event_counts['typeId'].eq('Take On').astype(int)
    event_counts['Ball Recoveries'] = event_counts['typeId'].eq('Ball recovery').astype(int)
    event_counts['Clearance'] = event_counts['typeId'].eq('Clearance').astype(int)
    event_counts['Interceptions'] = event_counts['typeId'].eq('Interception').astype(int)
    event_counts['Tackles'] = event_counts['typeId'].eq('Tackle').astype(int)

    event_counts['Blocks/Saves'] = event_counts['typeId'].eq('Save').astype(int)
    event_counts['Shots on Target'] = (
        event_counts['typeId'].eq('Goal') |
        (
            is_attempt_saved &
            event_counts['next_position'].astype(str).str.strip().eq('GK')
        )
    ).astype(int)
    event_counts['Yellow Card'] = event_counts['yellowcard'].eq(1).astype(int)
    event_counts['Red Card'] = (
        event_counts['yellowcard2'].eq(1) | event_counts['redcard'].eq(1)
    ).astype(int)
    event_counts['Own Goal'] = event_counts['typeId'].eq('Own Goal').astype(int)
    event_counts['Penalty Scored'] = (
        event_counts['typeId'].eq('Goal') & event_counts['penalty'].eq(1)
    ).astype(int)
    event_counts['Penalty Missed'] = (
        (
            is_attempt_saved |
            event_counts['typeId'].isin(['Post', 'Miss'])
        ) &
        event_counts['penalty'].eq(1)
    ).astype(int)
    event_counts['Penalty Saved'] = (
        event_counts['typeId'].eq('Save') & event_counts['penalty'].eq(1)
    ).astype(int)

    player_event_counts = (
        event_counts
        .groupby('playerName', as_index=False)[count_columns]
        .sum()
    )

    starting_lineups['player_name'] = starting_lineups['player_name'].astype(str).str.strip()
    player_event_counts = player_event_counts.set_index('playerName')
    for col in count_columns:
        starting_lineups[col] = (
            starting_lineups['player_name']
            .map(player_event_counts[col])
            .fillna(0)
            .astype(int)
        )

    shootout_scores = shootout_scores.copy()
    if not shootout_scores.empty:
        shootout_scores['playerName'] = shootout_scores['playerName'].astype(str).str.strip()
        shootout_lookup = shootout_scores.set_index('playerName')['Shootout']
        starting_lineups['Shootout'] = (
            starting_lineups['player_name'].astype(str).str.strip().map(shootout_lookup).fillna(0).astype(int)
        )
    else:
        starting_lineups['Shootout'] = 0


    playerlist = pd.read_excel(playerlist_path)

    # Standardise player IDs before matching.
    starting_lineups['player_id'] = starting_lineups['player_id'].astype(str).str.strip()
    playerlist['player_id'] = playerlist['player_id'].astype(str).str.strip()

    position_lookup = (
        playerlist[['player_id', 'BnC Position']]
        .drop_duplicates(subset='player_id')
    )

    starting_lineups = starting_lineups.drop(
        columns=['BnC Position'],
        errors='ignore'
    ).merge(
        position_lookup,
        on='player_id',
        how='left'
    )

    starting_lineups['BnC Position'] = (
        starting_lineups['BnC Position']
        .fillna('')
        .astype(str)
        .str.strip()
        .str.upper()
    )

    defcons_base = starting_lineups[
        ['Clearance', 'Interceptions', 'Blocks/Saves', 'Tackles']
    ].fillna(0).sum(axis=1)

    starting_lineups['DEFCONS'] = np.select(
        [
            starting_lineups['BnC Position'].eq('GK'),
            starting_lineups['BnC Position'].eq('DEF'),
            starting_lineups['BnC Position'].isin(['MID', 'FWD'])
        ],
        [
            0,
            defcons_base,
            defcons_base + starting_lineups['Ball Recoveries'].fillna(0)
        ],
        default=0
    )

    starting_lineups['ATTCONS'] = starting_lineups[
        ['Key Passes', 'Shots on Target', 'Dribbles']
    ].fillna(0).sum(axis=1)


    def calculate_fantasy_score(row):
        position = row['BnC Position']

        # Unknown or missing positions receive no score.
        if position not in ['GK', 'DEF', 'MID', 'FWD']:
            return 0

        minutes = row['minutes_played']
        goals = row['Goals']
        assists = row['Assists']
        conceded = row['goals_conceded']

        score = 3 if minutes >= 120 else 2 if minutes >= 60 else 1

        if row['Red Card'] >= 1:
            score -= 3
        elif row['Yellow Card'] >= 1:
            score -= 1

        if position == 'GK':
            score += goals * 20
            score += assists * 10
            score += row['Blocks/Saves'] * 0.5
            score -= conceded * 0.5

            if minutes >= 60 and conceded == 0:
                score += 4
            if row['Penalty Saved'] >= 1:
                score += 3

        elif position == 'DEF':
            score += goals * 6
            score += assists * 4
            score -= conceded * 0.5

            if goals >= 3:
                score += 3
            if assists >= 3:
                score += 3
            if row['DEFCONS'] >= 10:
                score += 2
            if row['ATTCONS'] >= 10:
                score += 2
            if minutes >= 60 and conceded == 0:
                score += 4
            if row['Penalty Missed'] >= 1:
                score -= 3
            if row['Own Goal'] >= 1:
                score -= 3

        elif position == 'MID':
            score += goals * 5
            score += assists * 3

            if goals >= 3:
                score += 3
            if assists >= 3:
                score += 3
            if row['DEFCONS'] >= 12:
                score += 2
            if row['ATTCONS'] >= 10:
                score += 2
            if minutes >= 60 and conceded == 0:
                score += 1
            if row['Penalty Missed'] >= 1:
                score -= 3
            if row['Own Goal'] >= 1:
                score -= 3

        elif position == 'FWD':
            score += goals * 4
            score += assists * 3

            if goals >= 3:
                score += 3
            if assists >= 3:
                score += 3
            if row['DEFCONS'] >= 12:
                score += 2
            if row['ATTCONS'] >= 10:
                score += 2
            if row['Penalty Missed'] >= 1:
                score -= 3
            if row['Own Goal'] >= 1:
                score -= 3

        return score


    starting_lineups['Match Score'] = starting_lineups.apply(
        calculate_fantasy_score,
        axis=1
    )
    starting_lineups['Total Score'] = (
        starting_lineups['Match Score'] + starting_lineups['Shootout']
    )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f'{matchlink}_playerlog.xlsx'
    starting_lineups.to_excel(output_path, index=False)
    return output_path
