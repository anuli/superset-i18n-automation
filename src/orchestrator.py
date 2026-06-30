"""
Core orchestration: receive an issue event, create a Devin session, track it.
"""

import requests

from src import devin_client, github_client
from src.config import COSMETIC_LABEL, DEVIN_API_TOKEN, GITHUB_TOKEN
from src.db import (
    get_active_sessions,
    get_sessions_for_issue,
    get_sessions_needing_screenshots,
    log_event,
    save_issue,
    save_session,
    update_screenshot_status,
    update_session_status,
)
from src.prompt_builder import (
    build_cosmetic_fix_prompt,
    build_screenshot_verification_prompt,
)


def handle_issue(issue_number: int, issue_url: str, title: str,
                 body: str | None, labels: list[str]) -> dict:
    """Process a single cosmetic-bug issue end-to-end.

    Returns a summary dict with session info or a skip reason.
    """
    if COSMETIC_LABEL not in labels:
        log_event("issue_skipped", issue_number=issue_number,
                  details={"reason": "missing_label"})
        return {"skipped": True, "reason": "missing cosmetic label"}

    existing = get_sessions_for_issue(issue_number)
    if existing:
        log_event("issue_skipped", issue_number=issue_number,
                  details={"reason": "session_exists",
                           "session_id": existing[0]["session_id"]})
        return {"skipped": True, "reason": "session already exists",
                "existing_session": existing[0]["session_url"]}

    issue_id = save_issue(issue_number, issue_url, title, body, labels)
    log_event("issue_received", issue_number=issue_number)

    prompt = build_cosmetic_fix_prompt(issue_number, title, body)
    tags = ["cosmetic-fix", f"issue:{issue_number}"]

    try:
        result = devin_client.create_session(prompt, tags=tags)
    except requests.RequestException as exc:
        log_event("session_create_failed", issue_number=issue_number,
                  details={"error": str(exc)})
        return {"error": str(exc)}

    session_id = result.get("session_id", "")
    session_url = result.get("url",
                             f"https://app.devin.ai/sessions/{session_id}")

    save_session(issue_id, session_id, session_url, prompt)
    log_event("session_created", issue_number=issue_number,
              session_id=session_id)

    if GITHUB_TOKEN:
        try:
            github_client.add_comment(
                issue_number,
                f"Devin session created to fix this cosmetic bug.\n"
                f"Session: {session_url}",
            )
        except requests.RequestException:
            pass

    return {
        "session_id": session_id,
        "session_url": session_url,
        "issue_number": issue_number,
    }


def sync_session_statuses() -> list[dict]:
    """Poll the Devin API and update local status for active sessions."""
    active = get_active_sessions()
    updated: list[dict] = []

    for session in active:
        try:
            data = devin_client.get_session(session["session_id"])
        except requests.RequestException:
            continue

        new_status = data.get("status_enum", data.get("status", "unknown"))
        pr_url = None
        pr = data.get("pull_request")
        if pr:
            pr_url = pr.get("url")

        if new_status != session["status"] or (pr_url and not session.get("pr_url")):
            update_session_status(session["session_id"], new_status, pr_url)
            log_event("session_status_changed",
                      issue_number=session.get("github_issue_number"),
                      session_id=session["session_id"],
                      details={"old": session["status"], "new": new_status,
                               "pr_url": pr_url})
            updated.append({
                "session_id": session["session_id"],
                "old_status": session["status"],
                "new_status": new_status,
                "pr_url": pr_url,
            })

    return updated


def backfill_open_issues() -> list[dict]:
    """Fetch all open issues with the cosmetic label and process any
    that don't already have a session."""
    issues = github_client.list_issues_by_label(COSMETIC_LABEL)
    results: list[dict] = []
    for issue in issues:
        labels = [l["name"] for l in issue.get("labels", [])]
        res = handle_issue(
            issue_number=issue["number"],
            issue_url=issue["html_url"],
            title=issue["title"],
            body=issue.get("body"),
            labels=labels,
        )
        results.append(res)
    return results


def create_screenshot_session() -> dict | None:
    """Create a single Devin session to screenshot-verify all PRs that
    haven't been verified yet.

    Returns session info dict, or None if there are no PRs to verify.
    """
    sessions = get_sessions_needing_screenshots()
    if not sessions:
        return None

    pr_entries: list[dict] = []
    for s in sessions:
        pr_url = s["pr_url"]
        pr_number = pr_url.rstrip("/").split("/")[-1] if pr_url else ""
        pr_entries.append({
            "issue_number": s["github_issue_number"],
            "title": s["issue_title"],
            "pr_url": pr_url,
            "pr_number": pr_number,
            "branch": f"devin/fix-issue-{s['github_issue_number']}",
        })

    prompt = build_screenshot_verification_prompt(pr_entries)
    tags = ["screenshot-verification"]

    try:
        result = devin_client.create_session(prompt, tags=tags)
    except requests.RequestException as exc:
        log_event("screenshot_session_failed",
                  details={"error": str(exc),
                           "pr_count": len(pr_entries)})
        for s in sessions:
            update_screenshot_status(s["session_id"], "error")
        return {"error": str(exc)}

    session_id = result.get("session_id", "")
    session_url = result.get("url",
                             f"https://app.devin.ai/sessions/{session_id}")

    for s in sessions:
        update_screenshot_status(s["session_id"], "in_progress")

    log_event("screenshot_session_created",
              session_id=session_id,
              details={"pr_count": len(pr_entries),
                       "pr_numbers": [e["pr_number"] for e in pr_entries]})

    return {
        "session_id": session_id,
        "session_url": session_url,
        "pr_count": len(pr_entries),
    }
