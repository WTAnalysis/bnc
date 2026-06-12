from __future__ import annotations

import base64
from pathlib import Path

import requests


def upload_file(
    local_path: Path,
    repository: str,
    token: str,
    branch: str = "main",
    remote_directory: str = "bnc-streamlit-app/data/points",
) -> str:
    """Create or update a file through the GitHub Contents API."""
    repository = repository.strip()
    token = token.strip()
    branch = branch.strip()
    remote_path = f"{remote_directory.strip('/')}/{local_path.name}"
    url = f"https://api.github.com/repos/{repository}/contents/{remote_path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    params = {"ref": branch}
    existing = requests.get(url, headers=headers, params=params, timeout=30)
    sha = existing.json().get("sha") if existing.ok else None

    payload = {
        "message": f"Add points for {local_path.stem}",
        "content": base64.b64encode(local_path.read_bytes()).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    response = requests.put(url, headers=headers, json=payload, timeout=45)
    response.raise_for_status()
    return response.json()["content"]["html_url"]
