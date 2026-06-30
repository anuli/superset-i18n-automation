"""
Lightweight GitHub API helpers.
"""

import requests

from src.config import GITHUB_TOKEN, SUPERSET_REPO

_API_BASE = "https://api.github.com"
_STATUS_ISSUE_TITLE = "Automation Status Report"
_STATUS_LABEL = "automation-status"


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


def _ensure_label(label: str) -> None:
    """Create the label if it doesn't exist (ignore 422 = already exists)."""
    resp = requests.post(
        f"{_API_BASE}/repos/{SUPERSET_REPO}/labels",
        headers=_headers(),
        json={"name": label, "color": "0e8a16", "description": "Automation status reports"},
        timeout=15,
    )
    if resp.status_code not in (201, 422):
        resp.raise_for_status()


def find_or_create_status_issue() -> int:
    """Find the open automation-status issue, or create one. Returns issue number."""
    issues = list_issues_by_label(_STATUS_LABEL, state="open")
    if issues:
        return issues[0]["number"]

    _ensure_label(_STATUS_LABEL)
    resp = requests.post(
        f"{_API_BASE}/repos/{SUPERSET_REPO}/issues",
        headers=_headers(),
        json={
            "title": _STATUS_ISSUE_TITLE,
            "body": (
                "This issue tracks the status of the cosmetic-bug automation. "
                "Each run posts a summary comment below.\n\n"
                "**Do not close this issue** — the automation appends reports here."
            ),
            "labels": [_STATUS_LABEL],
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["number"]


def post_status_report(body: str) -> dict:
    """Post a markdown report as a comment on the automation-status issue."""
    issue_number = find_or_create_status_issue()
    return add_comment(issue_number, body)
