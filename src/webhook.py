"""
Flask server handling GitHub webhook events and serving the observability
dashboard.
"""

import hashlib
import hmac
import time
from datetime import datetime, timezone

from flask import Flask, Response, jsonify, request

from src.config import COSMETIC_LABEL, SUPERSET_REPO, WEBHOOK_SECRET
from src.db import (
    get_all_sessions,
    get_recent_events,
    get_session_stats,
    init_db,
)
from src.orchestrator import (
    create_screenshot_session,
    handle_issue,
    sync_session_statuses,
)

app = Flask(__name__)


def _verify_signature(payload: bytes, signature: str) -> bool:
    """Verify the GitHub webhook HMAC-SHA256 signature."""
    if not WEBHOOK_SECRET:
        return True
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ------------------------------------------------------------------
# Webhook endpoint
# ------------------------------------------------------------------

@app.route("/webhook", methods=["POST"])
def webhook() -> tuple[Response, int]:
    """Handle GitHub issue webhook events.

    Triggers on:
      - issues / opened   (if the issue already has the cosmetic label)
      - issues / labeled   (when the cosmetic label is added)
    """
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_signature(request.data, signature):
        return jsonify({"error": "Invalid signature"}), 403

    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        return jsonify({"message": "pong"}), 200

    if event != "issues":
        return jsonify({"message": f"Ignored event: {event}"}), 200

    payload = request.get_json(silent=True) or {}
    action = payload.get("action", "")

    if action not in ("opened", "labeled"):
        return jsonify({"message": f"Ignored action: {action}"}), 200

    issue = payload.get("issue", {})
    labels = [l["name"] for l in issue.get("labels", [])]

    if action == "labeled":
        added_label = payload.get("label", {}).get("name", "")
        if added_label != COSMETIC_LABEL:
            return jsonify({"message": f"Ignored label: {added_label}"}), 200

    if COSMETIC_LABEL not in labels:
        return jsonify({"message": "Issue missing cosmetic label"}), 200

    repo_name = payload.get("repository", {}).get("full_name", "")
    if repo_name != SUPERSET_REPO:
        return jsonify({"message": f"Ignored repo: {repo_name}"}), 200

    result = handle_issue(
        issue_number=issue["number"],
        issue_url=issue.get("html_url", ""),
        title=issue.get("title", ""),
        body=issue.get("body"),
        labels=labels,
    )

    status_code = 201 if "session_id" in result else 200
    return jsonify(result), status_code


# ------------------------------------------------------------------
# Observability endpoints
# ------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health() -> Response:
    return jsonify({"status": "ok", "timestamp": time.time()})


@app.route("/report", methods=["GET"])
def report_json() -> Response:
    """JSON observability report."""
    stats = get_session_stats()
    sessions = get_all_sessions()
    events = get_recent_events(limit=30)

    return jsonify({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
        "sessions": [
            {
                "session_id": s["session_id"],
                "session_url": s["session_url"],
                "issue_number": s["github_issue_number"],
                "issue_title": s["issue_title"],
                "status": s["status"],
                "pr_url": s["pr_url"],
                "created_at": s["created_at"],
            }
            for s in sessions
        ],
        "recent_events": events,
    })


@app.route("/report/text", methods=["GET"])
def report_text() -> Response:
    """Plain-text observability dashboard for engineering leadership."""
    stats = get_session_stats()
    sessions = get_all_sessions()
    events = get_recent_events(limit=20)

    lines = [
        "=" * 64,
        "  SUPERSET COSMETIC-BUG AUTOMATION REPORT",
        "=" * 64,
        f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "--- Summary ---",
        f"  Issues tracked:        {stats['total_issues_tracked']}",
        f"  Devin sessions total:  {stats['total_sessions']}",
        f"  Sessions with PRs:     {stats['sessions_with_prs']}",
    ]
    for status, count in stats.get("by_status", {}).items():
        lines.append(f"    {status}: {count}")

    if stats["total_sessions"] > 0:
        success_rate = stats["sessions_with_prs"] / stats["total_sessions"] * 100
        lines.append(f"  PR success rate:       {success_rate:.0f}%")
    lines.append("")

    if sessions:
        lines.append("--- Sessions ---")
        for s in sessions[:20]:
            pr_str = f" -> {s['pr_url']}" if s.get("pr_url") else ""
            lines.append(
                f"  [{s['status']:>10s}] #{s['github_issue_number']} "
                f"{s['issue_title'][:50]}{pr_str}"
            )
            lines.append(f"             {s['session_url']}")
        lines.append("")

    if events:
        lines.append("--- Recent Events ---")
        for e in events[:15]:
            ts = datetime.fromtimestamp(
                e["timestamp"], tz=timezone.utc
            ).strftime("%m-%d %H:%M")
            issue_str = f" #{e['issue_number']}" if e.get("issue_number") else ""
            lines.append(f"  {ts}  {e['event_type']}{issue_str}")
        lines.append("")

    lines.append("=" * 64)
    return Response("\n".join(lines), mimetype="text/plain")


@app.route("/sessions/sync", methods=["POST"])
def sync_sessions() -> Response:
    """Trigger a status sync for all active sessions."""
    updated = sync_session_statuses()
    return jsonify({"updated": updated})


@app.route("/sessions/verify", methods=["POST"])
def verify_screenshots() -> tuple[Response, int]:
    """Create a screenshot verification session for unverified PRs."""
    result = create_screenshot_session()
    if result is None:
        return jsonify({"message": "No PRs need verification"}), 200
    if "error" in result:
        return jsonify({"error": result["error"]}), 500
    return jsonify(result), 201


def create_app() -> Flask:
    """Create and configure the Flask app."""
    init_db()
    return app
