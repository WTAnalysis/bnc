from __future__ import annotations

import base64

import pandas as pd
import requests


def commit_scores(
    scores: pd.DataFrame,
    *,
    token: str,
    repo: str,
    branch: str = "main",
    path: str = "data/match_scores.csv",
) -> str:
    api_url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    current = requests.get(
        api_url,
        headers=headers,
        params={"ref": branch},
        timeout=30,
    )
    sha = current.json().get("sha") if current.ok else None
    content = base64.b64encode(scores.to_csv(index=False).encode("utf-8")).decode("ascii")
    payload = {
        "message": "Update completed match scores",
        "content": content,
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    response = requests.put(api_url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()["commit"]["html_url"]
