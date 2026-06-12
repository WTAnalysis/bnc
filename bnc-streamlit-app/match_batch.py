from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd

from config import (
    EVENTS_PATH,
    FORMATION_PATH,
    PLAYERLIST_PATH,
    POINTS_DIR,
    QUALIFIERS_PATH,
)
from scoring_engine import process_match


def process_matches(
    matches: pd.DataFrame,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> list[dict]:
    results = []
    total = len(matches)

    for index, row in enumerate(matches.itertuples(index=False), start=1):
        match_id = str(row.matchlink).strip()
        if progress_callback:
            progress_callback(index, total, match_id)
        try:
            output_path = process_match(
                matchlink=match_id,
                output_dir=POINTS_DIR,
                formation_dict_path=FORMATION_PATH,
                events_path=EVENTS_PATH,
                qualifiers_path=QUALIFIERS_PATH,
                playerlist_path=PLAYERLIST_PATH,
            )
            results.append(
                {"match_id": match_id, "success": True, "path": Path(output_path), "error": ""}
            )
        except Exception as exc:
            results.append(
                {"match_id": match_id, "success": False, "path": None, "error": str(exc)}
            )
    return results
