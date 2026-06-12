from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
COMPETITION_PATH = DATA_DIR / "BnC World Cup 2026.xlsx"
PLAYERLIST_PATH = DATA_DIR / "playerlist.xlsx"
SCORES_PATH = DATA_DIR / "match_scores.csv"

COMPETITOR_SHEETS = [
    "Barlow",
    "Taylor",
    "Ian",
    "WillT",
    "Joe",
    "Dan",
    "Andy",
    "WillS",
]

COMPETITOR_NAMES = {
    "Barlow": "Barlow",
    "Taylor": "Taylor",
    "Ian": "Ian",
    "WillT": "Will T",
    "Joe": "Joe",
    "Dan": "Dan",
    "Andy": "Andy",
    "WillS": "Will S",
}

STAGES = [
    "G1",
    "G2",
    "G3",
    "Last 32",
    "Last 16",
    "Quarter Final",
    "Semi Final",
    "3rd Place / Final",
]

SCORE_COLUMNS = [
    "match_id",
    "match_datetime",
    "stage",
    "fixture",
    "player_id",
    "player_name",
    "nation",
    "team",
    "minutes",
    "goals",
    "assists",
    "key_passes",
    "dribbles",
    "ball_recoveries",
    "clearances",
    "interceptions",
    "tackles",
    "blocks_saves",
    "shots_on_target",
    "yellow_cards",
    "red_cards",
    "own_goals",
    "penalties_missed",
    "penalties_saved",
    "goals_conceded",
    "defcons",
    "attcons",
    "points",
    "processed_at",
]
