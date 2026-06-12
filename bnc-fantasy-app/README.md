# BnC World Cup Fantasy

A public Streamlit app that:

- reads the current schedule and stage selections from the OneDrive workbook;
- processes completed Opta/Perform matches from the previous 48 hours;
- commits stable per-match player scores to `data/match_scores.csv` on GitHub;
- displays an overall league table, one tab per stage, and a completed-match selector.

## Repository setup

1. Put this folder in a GitHub repository.
2. Keep `data/playerlist.xlsx` and `data/match_scores.csv` in the repository.
3. Deploy `app.py` on Streamlit Community Cloud.
4. Add the values from `.streamlit/secrets.example.toml` to the app's Streamlit secrets.

## OneDrive requirement

The supplied `1drv.ms` link currently returns an authentication/blocked response to
non-browser clients. In OneDrive, share the workbook as **Anyone with the link can
view**, obtain an anonymous direct-download URL, and set it as
`ONEDRIVE_DOWNLOAD_URL`.

The app never edits the OneDrive workbook. It treats that workbook as the live source
for schedule and team selections.

## GitHub persistence

Streamlit Cloud's local filesystem is temporary, so persistence uses the GitHub
Contents API. Create a fine-grained token with **Contents: Read and write** access to
this repository and configure:

```toml
GITHUB_TOKEN = "github_pat_..."
GITHUB_REPO = "owner/repository"
GITHUB_BRANCH = "main"
```

An admin enters `ADMIN_PASSWORD` in the sidebar and clicks **Process recent matches**.
Only matches with kick-off times between 2 and 48 hours ago, and not already present
in the cache, are processed.

## Selection rules

- `Picked`, `Captain`, and `Vice Captain` are active selections.
- Labels beginning with `Sub` score zero.
- `Captain` points are doubled.
- `Vice Captain` currently scores normally; automatic captain replacement can be
  added once the competition's no-appearance rule is confirmed.

## Local run

```powershell
pip install -r requirements.txt
Copy-Item .streamlit/secrets.example.toml .streamlit/secrets.toml
streamlit run app.py
```

## Scoring

The scoring engine is the deployable version of the final fantasy score section in
the supplied notebook. It calculates appearances, goals, assists, cards, clean
sheets, goals conceded, penalties, DEFCONS, ATTCONS, and the position-specific point
rules using `player_id` and `BnC Position`.
