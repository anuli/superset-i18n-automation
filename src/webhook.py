"""
Flask webhook server for GitHub push events and observability reporting.
"""

import hashlib
import hmac
import json
import threading
import time
from datetime import datetime, timezone

from flask import Flask, Response, jsonify, request

from src.config import COVERAGE_THRESHOLD, SUPERSET_BRANCH, SUPERSET_REPO, WEBHOOK_SECRET
from src.db import (
    get_all_sessions,
    get_coverage_trend,
    get_latest_scan,
    get_scan_history,
    get_session_stats,
    init_db,
)
from src.orchestrator import (
    create_locale_fix_sessions,
    create_unwrapped_fix_session,
    sync_session_statuses,
)
from src.scanner import run_scan

app = Flask(__name__)


def _verify_signature(payload: bytes, signature: str) -> bool:
    """Verify GitHub webhook signature."""
    if not WEBHOOK_SECRET:
        return True
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _run_scan_and_fix(trigger_type: str, fix: bool = True) -> dict:
    """Run scan and optionally create fix sessions. Returns summary."""
    from src.db import save_scan

    scan_result = run_scan()
    scan_id = save_scan(scan_result, trigger_type=trigger_type)

    summary = {
        "scan_id": scan_id,
        "commit_sha": scan_result.commit_sha,
        "pot_total_strings": scan_result.pot_total_strings,
        "locale_coverages": [
            {
                "locale": c.locale,
                "coverage_pct": c.coverage_pct,
                "translated": c.translated,
                "untranslated": c.untranslated,
            }
            for c in scan_result.locale_coverages
        ],
        "unwrapped_strings_count": len(scan_result.unwrapped_strings),
        "sessions_created": [],
    }

    if fix:
        locale_sessions = create_locale_fix_sessions(
            scan_id, scan_result, threshold=COVERAGE_THRESHOLD
        )
        summary["sessions_created"].extend(locale_sessions)

        if scan_result.unwrapped_strings:
            unwrapped_session = create_unwrapped_fix_session(scan_id, scan_result)
            if unwrapped_session:
                summary["sessions_created"].append(unwrapped_session)

    return summary


@app.route("/health", methods=["GET"])
def health() -> Response:
    return jsonify({"status": "ok", "timestamp": time.time()})


@app.route("/webhook", methods=["POST"])
def webhook() -> tuple[Response, int]:
    """Handle GitHub push webhook events."""
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_signature(request.data, signature):
        return jsonify({"error": "Invalid signature"}), 403

    event = request.headers.get("X-GitHub-Event", "")
    if event != "push":
        return jsonify({"message": f"Ignored event: {event}"}), 200

    payload = request.get_json(silent=True) or {}

    ref = payload.get("ref", "")
    repo_name = payload.get("repository", {}).get("full_name", "")

    expected_ref = f"refs/heads/{SUPERSET_BRANCH}"
    if ref != expected_ref:
        return jsonify({"message": f"Ignored ref: {ref}"}), 200

    if repo_name != SUPERSET_REPO:
        return jsonify({"message": f"Ignored repo: {repo_name}"}), 200

    def async_scan() -> None:
        try:
            _run_scan_and_fix(trigger_type="webhook", fix=True)
        except Exception as e:
            print(f"[ERROR] Webhook scan failed: {e}")

    thread = threading.Thread(target=async_scan, daemon=True)
    thread.start()

    return jsonify({
        "message": "Scan triggered",
        "ref": ref,
        "repo": repo_name,
    }), 202


@app.route("/scan", methods=["POST"])
def manual_scan() -> tuple[Response, int]:
    """Trigger a manual scan via API."""
    fix = request.args.get("fix", "false").lower() == "true"
    summary = _run_scan_and_fix(trigger_type="api", fix=fix)
    return jsonify(summary), 200


@app.route("/report", methods=["GET"])
def report() -> Response:
    """Observability report endpoint."""
    latest_scan = get_latest_scan()
    session_stats = get_session_stats()
    scan_history = get_scan_history(limit=10)
    all_sessions = get_all_sessions()

    coverage_trends = {}
    if latest_scan:
        for cov in latest_scan.get("locale_coverages", []):
            locale = cov["locale"]
            coverage_trends[locale] = get_coverage_trend(locale, limit=10)

    report_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest_scan": latest_scan,
        "session_stats": session_stats,
        "scan_history": [
            {
                "id": s["id"],
                "timestamp": s["timestamp"],
                "commit_sha": s["commit_sha"],
                "trigger_type": s["trigger_type"],
                "unwrapped_count": s["unwrapped_count"],
                "coverages": s["locale_coverages"],
            }
            for s in scan_history
        ],
        "active_sessions": [
            {
                "session_id": s["session_id"],
                "session_url": s["session_url"],
                "locale": s["locale"],
                "task_type": s["task_type"],
                "status": s["status"],
                "pr_url": s["pr_url"],
                "created_at": s["created_at"],
            }
            for s in all_sessions
        ],
        "coverage_trends": coverage_trends,
    }
    return jsonify(report_data)


@app.route("/report/text", methods=["GET"])
def report_text() -> Response:
    """Human-readable text report for engineering leadership."""
    latest_scan = get_latest_scan()
    session_stats = get_session_stats()
    all_sessions = get_all_sessions()

    lines = [
        "=" * 60,
        "  SUPERSET i18n AUTOMATION REPORT",
        "=" * 60,
        f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]

    if latest_scan:
        lines.extend([
            "--- Latest Scan ---",
            f"  Commit:  {latest_scan['commit_sha'][:12]}",
            f"  Trigger: {latest_scan['trigger_type']}",
            f"  Total catalog strings: {latest_scan['pot_total_strings']}",
            f"  Unwrapped frontend strings: {latest_scan['unwrapped_count']}",
            "",
            "--- Translation Coverage by Locale ---",
        ])
        for cov in latest_scan.get("locale_coverages", []):
            bar_len = int(cov["coverage_pct"] / 2)
            bar = "#" * bar_len + "." * (50 - bar_len)
            flag = " !!!" if cov["coverage_pct"] < COVERAGE_THRESHOLD else ""
            lines.append(
                f"  {cov['locale']:>6s}  [{bar}] {cov['coverage_pct']:5.1f}%  "
                f"({cov['untranslated']} missing){flag}"
            )
        lines.append("")

    lines.extend([
        "--- Session Stats ---",
        f"  Total sessions created: {session_stats['total_sessions']}",
        f"  Sessions with PRs:      {session_stats['sessions_with_prs']}",
    ])
    for status, count in session_stats.get("by_status", {}).items():
        lines.append(f"    {status}: {count}")
    lines.append("")

    active = [s for s in all_sessions if s["status"] not in ("finished", "stopped", "error")]
    if active:
        lines.append("--- Active Sessions ---")
        for s in active:
            lines.append(
                f"  [{s['status']}] {s['task_type']} "
                f"(locale={s['locale'] or 'n/a'}) -> {s['session_url']}"
            )
        lines.append("")

    completed_with_prs = [s for s in all_sessions if s.get("pr_url")]
    if completed_with_prs:
        lines.append("--- PRs Created ---")
        for s in completed_with_prs:
            lines.append(f"  {s['pr_url']}  (locale={s['locale'] or 'n/a'})")
        lines.append("")

    lines.append("=" * 60)

    return Response("\n".join(lines), mimetype="text/plain")


@app.route("/sessions/sync", methods=["POST"])
def sync_sessions() -> Response:
    """Sync session statuses from Devin API."""
    updated = sync_session_statuses()
    return jsonify({"updated": updated})


def create_app() -> Flask:
    """Create and configure the Flask app."""
    init_db()
    return app
