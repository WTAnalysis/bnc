from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
WORKBOOK_PATH = DATA_DIR / "BnC World Cup 2026.xlsx"
POINTS_DIR = DATA_DIR / "points"
FORMATION_PATH = DATA_DIR / "formation_dict.xlsx"
EVENTS_PATH = DATA_DIR / "Opta Events.xlsx"
QUALIFIERS_PATH = DATA_DIR / "Opta Qualifiers.xlsx"
PLAYERLIST_PATH = DATA_DIR / "playerlist.xlsx"
LIVE_STATUS_PATH = DATA_DIR / "live_status.json"
POINTS_OVERRIDE_PATH = DATA_DIR / "PointsOverride.xlsx"
WC_BONUS_PATH = DATA_DIR / "wcbonus.xlsx"

MANAGER_SHEETS = {
    "Barlow": "Barlow",
    "Taylor": "Taylor",
    "Ian": "Ian",
    "Will T": "WillT",
    "Joe": "Joe",
    "Dan": "Dan",
    "Andy": "Andy",
    "Will S": "WillS",
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

STAGE_LABELS = {
    "G1": "Group 1",
    "G2": "Group 2",
    "G3": "Group 3",
    "Last 32": "Last 32",
    "Last 16": "Last 16",
    "Quarter Final": "Quarter-final",
    "Semi Final": "Semi-final",
    "3rd Place / Final": "Final / third-place",
}

SELECTION_MULTIPLIERS = {
    "Picked": 1.0,
    "Captain": 2.0,
    "Vice Captain": 1.0,
}

MATCH_COMPLETION_BUFFER_HOURS = 2.5
LIVE_REFRESH_WINDOW_HOURS = 5
