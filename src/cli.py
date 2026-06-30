"""
CLI interface for the cosmetic-bug automation.

Usage:
    python -m src.cli serve [--port PORT]
    python -m src.cli backfill
    python -m src.cli sync
    python -m src.cli report
    python -m src.cli report-github
    python -m src.cli process-issue ISSUE_NUMBER
"""

import argparse
import sys
from datetime import datetime, timezone

from src.config import COSMETIC_LABEL, DEVIN_API_TOKEN, GITHUB_TOKEN, SUPERSET_REPO
from src.db import (
    get_all_sessions,
    get_recent_events,
    get_session_stats,
    init_db,
)


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the webhook server."""
    from src.webhook import create_app

    app = create_app()
    print(f"Starting webhook server on port {args.port}...")
    print(f"  Webhook:    http://localhost:{args.port}/webhook")
    print(f"  Report:     http://localhost:{args.port}/report")
    print(f"  Text report:http://localhost:{args.port}/report/text")
    print(f"  Health:     http://localhost:{args.port}/health")
    app.run(host="0.0.0.0", port=args.port, debug=args.debug)


def cmd_backfill(args: argparse.Namespace) -> None:
    """Fetch open cosmetic issues and create sessions for any missing."""
    init_db()

    if not DEVIN_API_TOKEN:
        print("[ERROR] DEVIN_API_TOKEN not set.")
        sys.exit(1)

    from src.orchestrator import backfill_open_issues

    print(f"Fetching open '{COSMETIC_LABEL}' issues from {SUPERSET_REPO}...")
    results = backfill_open_issues()
    created = [r for r in results if "session_id" in r]
    skipped = [r for r in results if r.get("skipped")]
    errors = [r for r in results if "error" in r]

    print(f"  {len(created)} sessions created")
    for c in created:
        print(f"    #{c['issue_number']}: {c['session_url']}")
    if skipped:
        print(f"  {len(skipped)} skipped")
    if errors:
        print(f"  {len(errors)} errors")
        for e in errors:
            print(f"    {e['error']}")


def cmd_process_issue(args: argparse.Namespace) -> None:
    """Process a single issue by number."""
    init_db()

    if not DEVIN_API_TOKEN:
        print("[ERROR] DEVIN_API_TOKEN not set.")
        sys.exit(1)

    from src import github_client
    from src.orchestrator import handle_issue

    print(f"Fetching issue #{args.issue_number} from {SUPERSET_REPO}...")
    issue = github_client.get_issue(args.issue_number)
    labels = [l["name"] for l in issue.get("labels", [])]

    result = handle_issue(
        issue_number=issue["number"],
        issue_url=issue["html_url"],
        title=issue["title"],
        body=issue.get("body"),
        labels=labels,
    )

    if "session_id" in result:
        print(f"Session created: {result['session_url']}")
    elif result.get("skipped"):
        print(f"Skipped: {result['reason']}")
    elif "error" in result:
        print(f"Error: {result['error']}")


def cmd_sync(args: argparse.Namespace) -> None:
    """Sync session statuses from the Devin API."""
    init_db()

    if not DEVIN_API_TOKEN:
        print("[ERROR] DEVIN_API_TOKEN not set.")
        sys.exit(1)

    from src.orchestrator import sync_session_statuses

    print("Syncing session statuses...")
    updated = sync_session_statuses()
    if updated:
        for u in updated:
            pr_str = f" PR: {u['pr_url']}" if u.get("pr_url") else ""
            print(f"  {u['session_id']}: {u['old_status']} -> {u['new_status']}{pr_str}")
    else:
        print("  No updates.")


def cmd_verify(args: argparse.Namespace) -> None:
    """Create a screenshot verification session for unverified PRs."""
    init_db()

    if not DEVIN_API_TOKEN:
        print("[ERROR] DEVIN_API_TOKEN not set.")
        sys.exit(1)

    from src.orchestrator import create_screenshot_session

    print("Checking for PRs needing screenshot verification...")
    result = create_screenshot_session()
    if result is None:
        print("  No PRs need verification.")
    elif "error" in result:
        print(f"  Error: {result['error']}")
    else:
        print(f"  Verification session created for {result['pr_count']} PR(s)")
        print(f"  Session: {result['session_url']}")


def _fmt_dur(seconds: float | None) -> str:
    """Format seconds into a human-readable duration."""
    if seconds is None:
        return "N/A"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    return f"{minutes / 60:.1f}h"


def build_markdown_report(
    stats: dict, sessions: list[dict], events: list[dict],
) -> str:
    """Build a markdown report string suitable for GitHub issue comments."""
    total = stats["total_sessions"]
    prs = stats["sessions_with_prs"]
    rate = (prs / total * 100) if total > 0 else 0
    v = stats.get("verification", {})
    tp = stats.get("throughput", {})
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"## Automation Report — {now_str}",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Issues tracked | {stats['total_issues_tracked']} |",
        f"| Sessions created | {total} |",
        f"| PRs produced | {prs} |",
        f"| Success rate | {rate:.0f}% |",
        f"| Avg time to PR | {_fmt_dur(stats.get('avg_time_to_pr_seconds'))} |",
        f"| PRs verified | {v.get('verified', 0)} |",
        f"| Verification pending | {v.get('pending', 0)} |",
        f"| Verification errors | {v.get('errors', 0)} |",
        f"| PRs (last 24h) | {tp.get('prs_last_24h', 0)} |",
        f"| PRs (last 7d) | {tp.get('prs_last_7d', 0)} |",
        "",
        "### Status Breakdown",
        "",
        "| Status | Count |",
        "|--------|-------|",
    ]
    for status, count in stats.get("by_status", {}).items():
        lines.append(f"| {status} | {count} |")

    if sessions:
        lines += [
            "",
            "### Sessions",
            "",
            "| Issue | Title | Status | PR | Verified |",
            "|-------|-------|--------|-----|----------|",
        ]
        for s in sessions[:20]:
            pr_link = f"[PR]({s['pr_url']})" if s.get("pr_url") else "-"
            v_status = s.get("screenshot_status") or "pending"
            lines.append(
                f"| #{s['github_issue_number']} "
                f"| {s['issue_title'][:40]} "
                f"| {s['status']} "
                f"| {pr_link} "
                f"| {v_status} |"
            )

    if events:
        lines += [
            "",
            "<details><summary>Recent Events</summary>",
            "",
            "| Time | Event | Issue |",
            "|------|-------|-------|",
        ]
        for e in events[:15]:
            ts = datetime.fromtimestamp(
                e["timestamp"], tz=timezone.utc
            ).strftime("%m-%d %H:%M")
            issue_str = f"#{e['issue_number']}" if e.get("issue_number") else "-"
            lines.append(f"| {ts} | {e['event_type']} | {issue_str} |")
        lines.append("")
        lines.append("</details>")

    return "\n".join(lines)


def cmd_report(args: argparse.Namespace) -> None:
    """Print the observability report to stdout."""
    init_db()
    stats = get_session_stats()
    sessions = get_all_sessions()
    events = get_recent_events(limit=20)
    print(build_markdown_report(stats, sessions, events))


def cmd_report_github(args: argparse.Namespace) -> None:
    """Post the observability report as a comment on the status issue in GitHub."""
    init_db()

    if not GITHUB_TOKEN:
        print("[ERROR] GITHUB_TOKEN not set.")
        sys.exit(1)

    from src.github_client import post_status_report

    stats = get_session_stats()
    sessions = get_all_sessions()
    events = get_recent_events(limit=20)
    md = build_markdown_report(stats, sessions, events)

    print("Posting report to GitHub...")
    result = post_status_report(md)
    print(f"  Posted: {result.get('html_url', '(done)')}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Superset Cosmetic-Bug Automation",
        prog="python -m src.cli",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_p = subparsers.add_parser("serve", help="Start the webhook server")
    serve_p.add_argument("--port", type=int, default=8000)
    serve_p.add_argument("--debug", action="store_true")
    serve_p.set_defaults(func=cmd_serve)

    backfill_p = subparsers.add_parser(
        "backfill", help="Process all open cosmetic issues"
    )
    backfill_p.set_defaults(func=cmd_backfill)

    process_p = subparsers.add_parser(
        "process-issue", help="Process a single issue by number"
    )
    process_p.add_argument("issue_number", type=int)
    process_p.set_defaults(func=cmd_process_issue)

    sync_p = subparsers.add_parser("sync", help="Sync session statuses")
    sync_p.set_defaults(func=cmd_sync)

    verify_p = subparsers.add_parser(
        "verify", help="Create screenshot verification session for unverified PRs"
    )
    verify_p.set_defaults(func=cmd_verify)

    report_p = subparsers.add_parser("report", help="Show observability report")
    report_p.set_defaults(func=cmd_report)

    report_gh_p = subparsers.add_parser(
        "report-github", help="Post report to GitHub status issue"
    )
    report_gh_p.set_defaults(func=cmd_report_github)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
