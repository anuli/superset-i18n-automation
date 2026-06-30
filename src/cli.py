"""
CLI interface for the cosmetic-bug automation.

Usage:
    python -m src.cli serve [--port PORT]
    python -m src.cli backfill
    python -m src.cli sync
    python -m src.cli report
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


def _format_duration(seconds: float | None) -> str:
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


def cmd_report(args: argparse.Namespace) -> None:
    """Print the observability report."""
    init_db()

    stats = get_session_stats()
    sessions = get_all_sessions()
    events = get_recent_events(limit=20)

    print("=" * 64)
    print("  SUPERSET COSMETIC-BUG AUTOMATION REPORT")
    print("=" * 64)
    print(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print()

    # --- Pipeline Health ---
    print("--- Pipeline Health ---")
    total = stats["total_sessions"]
    prs = stats["sessions_with_prs"]
    rate = (prs / total * 100) if total > 0 else 0
    print(f"  Issues tracked:        {stats['total_issues_tracked']}")
    print(f"  Sessions created:      {total}")
    print(f"  PRs produced:          {prs}")
    print(f"  Success rate:          {rate:.0f}%")
    print(f"  Avg time to PR:        {_format_duration(stats.get('avg_time_to_pr_seconds'))}")
    print()

    # --- Status Breakdown ---
    print("--- Session Status ---")
    for status, count in stats.get("by_status", {}).items():
        bar = "#" * count
        print(f"  {status:>12s}: {count:>3d}  {bar}")
    print()

    # --- Verification ---
    v = stats.get("verification", {})
    print("--- Verification Status ---")
    print(f"  Verified (screenshots):  {v.get('verified', 0)}")
    print(f"  In progress:             {v.get('in_progress', 0)}")
    print(f"  Pending:                 {v.get('pending', 0)}")
    print(f"  Errors:                  {v.get('errors', 0)}")
    print()

    # --- Throughput ---
    tp = stats.get("throughput", {})
    print("--- Throughput ---")
    print(f"  Sessions (last 24h):     {tp.get('sessions_last_24h', 0)}")
    print(f"  Sessions (last 7d):      {tp.get('sessions_last_7d', 0)}")
    print(f"  PRs produced (last 24h): {tp.get('prs_last_24h', 0)}")
    print(f"  PRs produced (last 7d):  {tp.get('prs_last_7d', 0)}")
    print()

    # --- Sessions ---
    if sessions:
        print("--- Sessions ---")
        for s in sessions[:20]:
            pr_str = f" -> {s['pr_url']}" if s.get("pr_url") else ""
            v_status = s.get("screenshot_status") or "-"
            print(
                f"  [{s['status']:>10s}] [v:{v_status:>5s}] "
                f"#{s['github_issue_number']} "
                f"{s['issue_title'][:40]}{pr_str}"
            )
            print(f"             {s['session_url']}")
        print()

    # --- Recent Events ---
    if events:
        print("--- Recent Events ---")
        for e in events[:15]:
            ts = datetime.fromtimestamp(
                e["timestamp"], tz=timezone.utc
            ).strftime("%m-%d %H:%M")
            issue_str = f" #{e['issue_number']}" if e.get("issue_number") else ""
            print(f"  {ts}  {e['event_type']}{issue_str}")
        print()

    print("=" * 64)


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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
