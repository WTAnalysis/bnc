# BnC World Cup 2026 Streamlit app

This app reads the World Cup schedule, drafted players and eight manager lineup
sheets from `data/BnC World Cup 2026.xlsx`. It combines those selections with
the per-match files in `data/points` to show:

- the overall league table;
- manager performance in all eight stages;
- each manager's 16-player squad and stage lineup;
- player points, captain multipliers and lineup totals;
- fixture coverage and missing completed matches.

The `scoring_engine.py` calculation body is adapted directly from
`BnC Streamlit App.ipynb`. Its scoring calculations are unchanged. The wrapper
parameterizes the match ID and file paths so `match_batch.py` can process every
completed fixture whose points file is missing.

`BnC Streamlit Batch.ipynb` provides the same batch workflow for manual
notebook runs.

## Scoring rules

- `Picked`: 1x
- `Captain`: 2x
- `Vice Captain`: 1x
- substitutes: 0x

## Run locally

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Upload this folder's contents to the root of `WTAnalysis/bnc`.
2. In Streamlit Community Cloud, create an app using `app.py`.
3. Use Python 3.11 or 3.12.
4. Add the optional secrets below if generated points should be committed back
   to GitHub:

```toml
BNC_GITHUB_REPOSITORY = "WTAnalysis/bnc"
BNC_GITHUB_BRANCH = "main"
BNC_GITHUB_TOKEN = "your_fine_grained_token"
```

The token needs **Contents: Read and write** access only for the `bnc`
repository. Without it, the update button still works for the current app
session, but Streamlit Cloud's ephemeral filesystem may discard generated
files after a restart.

## Data update flow

The schedule supplies each fixture's UTC kickoff, stage and match ID. A fixture
becomes eligible 2.5 hours after kickoff. Clicking the update button:

1. skips every match already present in `data/points`;
2. runs the notebook-derived calculation once for each eligible missing match;
3. writes `<match_id>_playerlog.xlsx`;
4. refreshes all standings and lineups;
5. uploads the new file to GitHub when repository secrets are configured.

The completion buffer is configurable in `config.py`.

## Live matches

Workbook times are UTC. The dashboard converts them to `Europe/London`, so
summer fixtures display in BST and winter fixtures display in GMT.

On the **Match data** tab:

1. **Check live scores** queries provider status for fixtures near the current
   time. It displays the score, provider status, provider update time and the
   time the app checked the feed.
2. **Refresh live fantasy points** is enabled only when the provider confirms
   a match is live. It reruns the scoring engine and updates the standings with
   provisional points.
3. Run the match again after the provider reports `Played` to retain the final
   points file.

Live checks are deliberately button-driven so viewing or filtering the
dashboard does not repeatedly call the provider or silently alter standings.

Provider-confirmed ongoing fixtures are also included in **Fixture data
status**, even before their points workbook exists.

## Predictions

The **Predictions** tab reads the workbook's `Predictor` sheet. It awards:

- `W`: 3 points for a correct score;
- `D`: 1 point for a correct result;
- `L`: 0 points.

Manager result columns map as follows: Barlow/SBR, Taylor/ATR, Ian/IUR,
Will T/WTR, Joe/JSR, Dan/DWR, Andy/AMR and Will S/WSR. Save the workbook in
Excel before uploading it so the formula-result cells have current cached
values for Streamlit to read.
