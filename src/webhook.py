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


def _fmt_dur(seconds: float | None) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds is None:
        return "N/A"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = minutes / 60
    return f"{hours:.1f}h"


@app.route("/report/text", methods=["GET"])
def report_text() -> Response:
    """Plain-text observability dashboard for engineering leadership."""
    stats = get_session_stats()
    sessions = get_all_sessions()
    events = get_recent_events(limit=20)

    total = stats["total_sessions"]
    prs = stats["sessions_with_prs"]
    rate = (prs / total * 100) if total > 0 else 0
    v = stats.get("verification", {})
    tp = stats.get("throughput", {})

    lines = [
        "=" * 64,
        "  SUPERSET COSMETIC-BUG AUTOMATION REPORT",
        "=" * 64,
        f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "--- Pipeline Health ---",
        f"  Issues tracked:        {stats['total_issues_tracked']}",
        f"  Sessions created:      {total}",
        f"  PRs produced:          {prs}",
        f"  Success rate:          {rate:.0f}%",
        f"  Avg time to PR:        {_fmt_dur(stats.get('avg_time_to_pr_seconds'))}",
        "",
        "--- Session Status ---",
    ]
    for status, count in stats.get("by_status", {}).items():
        bar = "#" * count
        lines.append(f"  {status:>12s}: {count:>3d}  {bar}")
    lines.append("")

    lines += [
        "--- Verification Status ---",
        f"  Verified (screenshots):  {v.get('verified', 0)}",
        f"  In progress:             {v.get('in_progress', 0)}",
        f"  Pending:                 {v.get('pending', 0)}",
        f"  Errors:                  {v.get('errors', 0)}",
        "",
        "--- Throughput ---",
        f"  Sessions (last 24h):     {tp.get('sessions_last_24h', 0)}",
        f"  Sessions (last 7d):      {tp.get('sessions_last_7d', 0)}",
        f"  PRs produced (last 24h): {tp.get('prs_last_24h', 0)}",
        f"  PRs produced (last 7d):  {tp.get('prs_last_7d', 0)}",
        "",
    ]

    if sessions:
        lines.append("--- Sessions ---")
        for s in sessions[:20]:
            pr_str = f" -> {s['pr_url']}" if s.get("pr_url") else ""
            v_status = s.get("screenshot_status") or "-"
            lines.append(
                f"  [{s['status']:>10s}] [v:{v_status:>5s}] "
                f"#{s['github_issue_number']} "
                f"{s['issue_title'][:40]}{pr_str}"
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


@app.route("/dashboard", methods=["GET"])
def dashboard() -> Response:
    """HTML observability dashboard for engineering leadership."""
    stats = get_session_stats()
    sessions = get_all_sessions()
    events = get_recent_events(limit=20)

    total = stats["total_sessions"]
    prs = stats["sessions_with_prs"]
    rate = (prs / total * 100) if total > 0 else 0
    v = stats.get("verification", {})
    tp = stats.get("throughput", {})
    avg_time = stats.get("avg_time_to_pr_seconds")
    avg_str = _fmt_dur(avg_time)

    # Build session rows
    session_rows = ""
    for s in sessions[:30]:
        pr_link = (
            f'<a href="{s["pr_url"]}" target="_blank">PR</a>'
            if s.get("pr_url") else "-"
        )
        v_status = s.get("screenshot_status") or "pending"
        v_class = {
            "done": "badge-ok", "in_progress": "badge-warn",
            "error": "badge-err",
        }.get(v_status, "badge-pend")
        status_class = {
            "finished": "badge-ok", "created": "badge-pend",
            "running": "badge-warn", "error": "badge-err",
            "stopped": "badge-err",
        }.get(s["status"], "badge-pend")
        ts = datetime.fromtimestamp(
            s["created_at"], tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M")
        session_rows += f"""<tr>
            <td>#{s['github_issue_number']}</td>
            <td>{s['issue_title'][:50]}</td>
            <td><span class="badge {status_class}">{s['status']}</span></td>
            <td>{pr_link}</td>
            <td><span class="badge {v_class}">{v_status}</span></td>
            <td>{ts}</td>
            <td><a href="{s['session_url']}" target="_blank">view</a></td>
        </tr>"""

    # Build event rows
    event_rows = ""
    for e in events[:15]:
        ts = datetime.fromtimestamp(
            e["timestamp"], tz=timezone.utc
        ).strftime("%m-%d %H:%M")
        issue_str = f"#{e['issue_number']}" if e.get("issue_number") else "-"
        event_rows += f"""<tr>
            <td>{ts}</td>
            <td>{e['event_type']}</td>
            <td>{issue_str}</td>
        </tr>"""

    # Status breakdown for chart
    status_items = ""
    max_count = max((c for c in stats.get("by_status", {}).values()), default=1)
    for status, count in stats.get("by_status", {}).items():
        pct = (count / max_count * 100) if max_count > 0 else 0
        color = {
            "finished": "#22c55e", "created": "#a3a3a3",
            "running": "#f59e0b", "error": "#ef4444",
            "stopped": "#ef4444",
        }.get(status, "#a3a3a3")
        status_items += f"""<div class="bar-row">
            <span class="bar-label">{status}</span>
            <div class="bar-track">
                <div class="bar-fill" style="width:{pct}%;background:{color}"></div>
            </div>
            <span class="bar-val">{count}</span>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Cosmetic Bug Automation Dashboard</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         background:#0f172a; color:#e2e8f0; padding:24px; }}
  h1 {{ font-size:1.5rem; margin-bottom:4px; color:#f8fafc; }}
  .subtitle {{ color:#94a3b8; font-size:.85rem; margin-bottom:24px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
           gap:16px; margin-bottom:24px; }}
  .card {{ background:#1e293b; border-radius:12px; padding:20px;
           border:1px solid #334155; }}
  .card-label {{ font-size:.75rem; text-transform:uppercase; letter-spacing:.05em;
                 color:#94a3b8; margin-bottom:4px; }}
  .card-value {{ font-size:1.8rem; font-weight:700; color:#f8fafc; }}
  .card-value.green {{ color:#22c55e; }}
  .card-value.yellow {{ color:#f59e0b; }}
  .card-value.red {{ color:#ef4444; }}
  .section {{ background:#1e293b; border-radius:12px; padding:20px;
              border:1px solid #334155; margin-bottom:24px; }}
  .section h2 {{ font-size:1rem; margin-bottom:12px; color:#f8fafc; }}
  table {{ width:100%; border-collapse:collapse; font-size:.85rem; }}
  th {{ text-align:left; padding:8px 12px; color:#94a3b8; border-bottom:1px solid #334155;
       font-weight:500; }}
  td {{ padding:8px 12px; border-bottom:1px solid #1e293b; }}
  tr:hover {{ background:#334155; }}
  a {{ color:#60a5fa; text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  .badge {{ padding:2px 8px; border-radius:9999px; font-size:.75rem; font-weight:600; }}
  .badge-ok {{ background:#166534; color:#86efac; }}
  .badge-warn {{ background:#713f12; color:#fde047; }}
  .badge-err {{ background:#7f1d1d; color:#fca5a5; }}
  .badge-pend {{ background:#334155; color:#94a3b8; }}
  .bar-row {{ display:flex; align-items:center; margin-bottom:6px; }}
  .bar-label {{ width:80px; font-size:.8rem; color:#94a3b8; }}
  .bar-track {{ flex:1; height:20px; background:#0f172a; border-radius:4px; overflow:hidden; }}
  .bar-fill {{ height:100%; border-radius:4px; transition:width .3s; }}
  .bar-val {{ width:30px; text-align:right; font-size:.8rem; margin-left:8px; }}
  .two-col {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  @media(max-width:768px) {{ .two-col {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<h1>Superset Cosmetic-Bug Automation</h1>
<p class="subtitle">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
   &mdash; answers "Is this automation working?"</p>

<div class="grid">
  <div class="card">
    <div class="card-label">Issues Tracked</div>
    <div class="card-value">{stats['total_issues_tracked']}</div>
  </div>
  <div class="card">
    <div class="card-label">Sessions Created</div>
    <div class="card-value">{total}</div>
  </div>
  <div class="card">
    <div class="card-label">PRs Produced</div>
    <div class="card-value green">{prs}</div>
  </div>
  <div class="card">
    <div class="card-label">Success Rate</div>
    <div class="card-value {'green' if rate >= 80 else 'yellow' if rate >= 50 else 'red'}">{rate:.0f}%</div>
  </div>
  <div class="card">
    <div class="card-label">Avg Time to PR</div>
    <div class="card-value">{avg_str}</div>
  </div>
  <div class="card">
    <div class="card-label">PRs Verified</div>
    <div class="card-value green">{v.get('verified', 0)}</div>
  </div>
  <div class="card">
    <div class="card-label">PRs (last 24h)</div>
    <div class="card-value">{tp.get('prs_last_24h', 0)}</div>
  </div>
  <div class="card">
    <div class="card-label">PRs (last 7d)</div>
    <div class="card-value">{tp.get('prs_last_7d', 0)}</div>
  </div>
</div>

<div class="two-col">
  <div class="section">
    <h2>Session Status</h2>
    {status_items}
  </div>
  <div class="section">
    <h2>Verification Pipeline</h2>
    <div class="bar-row">
      <span class="bar-label">Verified</span>
      <div class="bar-track"><div class="bar-fill" style="width:{v.get('verified',0) / max(prs,1) * 100}%;background:#22c55e"></div></div>
      <span class="bar-val">{v.get('verified', 0)}</span>
    </div>
    <div class="bar-row">
      <span class="bar-label">In progress</span>
      <div class="bar-track"><div class="bar-fill" style="width:{v.get('in_progress',0) / max(prs,1) * 100}%;background:#f59e0b"></div></div>
      <span class="bar-val">{v.get('in_progress', 0)}</span>
    </div>
    <div class="bar-row">
      <span class="bar-label">Pending</span>
      <div class="bar-track"><div class="bar-fill" style="width:{v.get('pending',0) / max(prs,1) * 100}%;background:#a3a3a3"></div></div>
      <span class="bar-val">{v.get('pending', 0)}</span>
    </div>
    <div class="bar-row">
      <span class="bar-label">Errors</span>
      <div class="bar-track"><div class="bar-fill" style="width:{v.get('errors',0) / max(prs,1) * 100}%;background:#ef4444"></div></div>
      <span class="bar-val">{v.get('errors', 0)}</span>
    </div>
  </div>
</div>

<div class="section">
  <h2>Sessions</h2>
  <table>
    <thead><tr>
      <th>Issue</th><th>Title</th><th>Status</th><th>PR</th>
      <th>Verified</th><th>Created</th><th>Session</th>
    </tr></thead>
    <tbody>{session_rows}</tbody>
  </table>
</div>

<div class="section">
  <h2>Recent Events</h2>
  <table>
    <thead><tr><th>Time</th><th>Event</th><th>Issue</th></tr></thead>
    <tbody>{event_rows}</tbody>
  </table>
</div>

</body></html>"""

    return Response(html, mimetype="text/html")


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
