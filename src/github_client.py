"""
Lightweight GitHub API helpers.
"""

import requests

from src.config import GITHUB_TOKEN, SUPERSET_REPO

_API_BASE = "https://api.github.com"


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def get_issue(issue_number: int) -> dict:
    """Fetch a single issue from the configured repo."""
    resp = requests.get(
        f"{_API_BASE}/repos/{SUPERSET_REPO}/issues/{issue_number}",
        headers=_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def list_issues_by_label(label: str, state: str = "open") -> list[dict]:
    """List open issues that carry a given label."""
    resp = requests.get(
        f"{_API_BASE}/repos/{SUPERSET_REPO}/issues",
        headers=_headers(),
        params={"labels": label, "state": state, "per_page": 100},
        timeout=15,
    )
    resp.raise_for_status()
    return [i for i in resp.json() if "pull_request" not in i]


def add_comment(issue_number: int, body: str) -> dict:
    """Post a comment on a GitHub issue."""
    resp = requests.post(
        f"{_API_BASE}/repos/{SUPERSET_REPO}/issues/{issue_number}/comments",
        headers=_headers(),
        json={"body": body},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()
