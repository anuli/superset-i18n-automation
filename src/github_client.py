"""
GitHub client using the `gh` CLI for issue and PR queries.
"""

import json
import subprocess
from dataclasses import dataclass

from src.config import SUPERSET_REPO


@dataclass
class Issue:
    number: int
    title: str
    url: str
    labels: list[str]


@dataclass
class PullRequest:
    number: int
    title: str
    url: str
    head_branch: str
    labels: list[str]


def _run_gh(args: list[str]) -> str:
    """Run a gh CLI command and return stdout."""
    result = subprocess.run(
        ["gh"] + args,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh command failed: {result.stderr}")
    return result.stdout


def get_open_issues(label: str) -> list[Issue]:
    """Fetch open issues with the given label from the superset repo."""
    output = _run_gh([
        "issue", "list",
        "--repo", SUPERSET_REPO,
        "--label", label,
        "--state", "open",
        "--json", "number,title,url,labels",
        "--limit", "100",
    ])
    data = json.loads(output) if output.strip() else []
    issues = []
    for item in data:
        issues.append(Issue(
            number=item["number"],
            title=item["title"],
            url=item["url"],
            labels=[lbl["name"] for lbl in item.get("labels", [])],
        ))
    return issues


def get_open_prs() -> list[PullRequest]:
    """Fetch all open PRs from the superset repo."""
    output = _run_gh([
        "pr", "list",
        "--repo", SUPERSET_REPO,
        "--state", "open",
        "--json", "number,title,url,headRefName,labels",
        "--limit", "100",
    ])
    data = json.loads(output) if output.strip() else []
    prs = []
    for item in data:
        prs.append(PullRequest(
            number=item["number"],
            title=item["title"],
            url=item["url"],
            head_branch=item.get("headRefName", ""),
            labels=[lbl["name"] for lbl in item.get("labels", [])],
        ))
    return prs


def get_pr_comments(pr_number: int) -> list[dict]:
    """Fetch comments on a PR."""
    output = _run_gh([
        "pr", "view",
        str(pr_number),
        "--repo", SUPERSET_REPO,
        "--json", "comments",
    ])
    data = json.loads(output) if output.strip() else {}
    return data.get("comments", [])


def _normalize(text: str) -> set[str]:
    """Extract meaningful words from text for fuzzy matching."""
    import re
    words = re.findall(r'[a-z]+', text.lower())
    stop_words = {"the", "a", "an", "in", "on", "is", "at", "to", "and", "or", "of", "for"}
    return {w for w in words if len(w) > 2 and w not in stop_words}


def issue_has_linked_pr(issue_number: int, open_prs: list[PullRequest]) -> bool:
    """Check if an issue has a linked PR (by issue reference, branch name, or title similarity)."""
    for pr in open_prs:
        # Direct reference
        if f"#{issue_number}" in pr.title or f"#{issue_number}" in pr.head_branch:
            return True
    # Fall back to title-based fuzzy matching
    return False


def find_linked_pr(issue_number: int, issue_title: str, open_prs: list[PullRequest]) -> PullRequest | None:
    """Find a PR linked to an issue by reference or title similarity."""
    issue_words = _normalize(issue_title)

    for pr in open_prs:
        # Direct reference
        if f"#{issue_number}" in pr.title or f"#{issue_number}" in pr.head_branch:
            return pr
        # Title similarity: if most issue words appear in the PR title
        pr_words = _normalize(pr.title)
        if issue_words and pr_words:
            overlap = len(issue_words & pr_words) / len(issue_words)
            if overlap >= 0.5:
                return pr
    return None
