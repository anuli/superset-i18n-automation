"""
CLI interface for the i18n automation.

Usage:
    python -m src.cli scan [--fix] [--threshold N]
    python -m src.cli report
    python -m src.cli sync
    python -m src.cli serve [--port PORT]
"""

import argparse
import sys
import time
from datetime import datetime, timezone

from src.config import COVERAGE_THRESHOLD, DEVIN_API_TOKEN, SUPERSET_BRANCH, SUPERSET_REPO
from src.db import (
    get_all_sessions,
    get_latest_scan,
    get_scan_history,
    get_session_stats,
    init_db,
    save_scan,
)
from src.scanner import run_scan


def cmd_scan(args: argparse.Namespace) -> None:
    """Run an i18n scan and optionally create fix sessions."""
    init_db()

    print(f"Scanning {SUPERSET_REPO} ({SUPERSET_BRANCH})...")
    print("Cloning/updating repository...")

    scan_result = run_scan(force_fresh=args.fresh)

    print(f"\nCommit: {scan_result.commit_sha[:12]}")
    print(f"Template strings (messages.pot): {scan_result.pot_total_strings}")
    print()

    print("Translation Coverage:")
    print("-" * 70)
    threshold = args.threshold or COVERAGE_THRESHOLD
    below_threshold = []

    for cov in scan_result.locale_coverages:
        bar_len = int(cov.coverage_pct / 2)
        bar = "#" * bar_len + "." * (50 - bar_len)
        flag = " <-- BELOW THRESHOLD" if cov.coverage_pct < threshold else ""
        print(f"  {cov.locale:>6s}  [{bar}] {cov.coverage_pct:5.1f}%  "
              f"({cov.untranslated} missing){flag}")
        if cov.coverage_pct < threshold:
            below_threshold.append(cov)

    print()
    print(f"Unwrapped frontend strings found: {len(scan_result.unwrapped_strings)}")

    if scan_result.unwrapped_strings:
        file_groups: dict[str, int] = {}
        for s in scan_result.unwrapped_strings:
            file_groups[s.file_path] = file_groups.get(s.file_path, 0) + 1
        print("  Top files:")
        for f, count in sorted(file_groups.items(), key=lambda x: -x[1])[:10]:
            print(f"    {f}: {count} strings")

    scan_id = save_scan(scan_result, trigger_type="cli")
    print(f"\nScan saved (id={scan_id})")

    if args.fix:
        from src.orchestrator import create_locale_fix_sessions, create_unwrapped_fix_session

        if not args.dry_run:
            from src.config import DEVIN_API_TOKEN
            if not DEVIN_API_TOKEN:
                print("\n[ERROR] DEVIN_API_TOKEN not set. Cannot create fix sessions.")
                print("Set it with: export DEVIN_API_TOKEN='your-token-here'")
                sys.exit(1)

        if below_threshold:
            print(f"\nCreating Devin sessions for {len(below_threshold)} locales below {threshold}%...")
            if args.dry_run:
                for cov in below_threshold[:3]:
                    print(f"  [DRY RUN] Would create session for {cov.locale} ({cov.coverage_pct}%)")
            else:
                sessions = create_locale_fix_sessions(
                    scan_id, scan_result, threshold=threshold
                )
                for s in sessions:
                    print(f"  Created session for {s['locale']}: {s['session_url']}")

        if scan_result.unwrapped_strings:
            print("\nCreating Devin session for unwrapped strings...")
            if args.dry_run:
                print(f"  [DRY RUN] Would create session for {len(scan_result.unwrapped_strings)} unwrapped strings")
            else:
                result = create_unwrapped_fix_session(scan_id, scan_result)
                if result:
                    print(f"  Created session: {result['session_url']}")
    else:
        if below_threshold:
            print(f"\n{len(below_threshold)} locale(s) below {threshold}% threshold.")
            print("Run with --fix to create Devin sessions to address these.")


def cmd_report(args: argparse.Namespace) -> None:
    """Print the observability report."""
    init_db()

    from src.db import get_tracked_issue_numbers, get_verified_pr_numbers, _ensure_cosmetic_tables

    latest_scan = get_latest_scan()
    session_stats = get_session_stats()
    all_sessions = get_all_sessions()
    scan_history = get_scan_history(limit=10)

    print("=" * 60)
    print("  SUPERSET i18n AUTOMATION REPORT")
    print("=" * 60)
    print(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print()

    if not latest_scan:
        print("  No i18n scans recorded yet. Run: python -m src.cli scan")
        print()
    else:
        print("--- Latest Scan ---")
        print(f"  Commit:  {latest_scan['commit_sha'][:12]}")
        print(f"  Trigger: {latest_scan['trigger_type']}")
        print(f"  Total catalog strings: {latest_scan['pot_total_strings']}")
        print(f"  Unwrapped frontend strings: {latest_scan['unwrapped_count']}")
        print()

        print("--- Translation Coverage ---")
        for cov in latest_scan.get("locale_coverages", []):
            bar_len = int(cov["coverage_pct"] / 2)
            bar = "#" * bar_len + "." * (50 - bar_len)
            print(f"  {cov['locale']:>6s}  [{bar}] {cov['coverage_pct']:5.1f}%  "
                  f"({cov['untranslated']} missing)")
        print()

    print("--- Session Stats ---")
    print(f"  Total sessions:    {session_stats['total_sessions']}")
    print(f"  Sessions with PRs: {session_stats['sessions_with_prs']}")
    for status, count in session_stats.get("by_status", {}).items():
        print(f"    {status}: {count}")
    print()

    if all_sessions:
        print("--- Recent Sessions ---")
        for s in all_sessions[:10]:
            locale_str = f"locale={s['locale']}" if s["locale"] else "frontend"
            pr_str = f" -> {s['pr_url']}" if s.get("pr_url") else ""
            print(f"  [{s['status']:>10s}] {s['task_type']} ({locale_str}){pr_str}")
            print(f"             {s['session_url']}")
        print()

    if len(scan_history) > 1:
        print("--- Scan History ---")
        for s in scan_history:
            ts = datetime.fromtimestamp(s["timestamp"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            print(f"  {ts}  commit={s['commit_sha'][:8]}  "
                  f"trigger={s['trigger_type']}  unwrapped={s['unwrapped_count']}")

    # Cosmetic bug tracking section
    _ensure_cosmetic_tables()
    tracked_issues = get_tracked_issue_numbers()
    verified_prs = get_verified_pr_numbers()
    print()
    print("--- Cosmetic Bug Tracking ---")
    print(f"  Tracked issues:   {len(tracked_issues)}")
    print(f"  Verified PRs:     {len(verified_prs)}")

    if tracked_issues:
        from src.db import get_db
        with get_db() as conn:
            rows = conn.execute(
                "SELECT issue_number, title, status FROM cosmetic_issues ORDER BY issue_number"
            ).fetchall()
        for row in rows:
            print(f"    Issue #{row['issue_number']}: [{row['status']}] {row['title']}")

    print()
    print("=" * 60)


def cmd_sync(args: argparse.Namespace) -> None:
    """Sync session statuses from Devin API."""
    init_db()

    all_sessions = get_all_sessions()
    active_sessions = [
        s for s in all_sessions
        if s["status"] not in ("finished", "stopped", "error")
    ]

    if not active_sessions:
        print("Syncing session statuses...")
        print("  No active sessions to sync.")
        return

    if not DEVIN_API_TOKEN:
        print("[ERROR] DEVIN_API_TOKEN not set. Cannot sync active sessions.")
        sys.exit(1)

    from src.orchestrator import sync_session_statuses

    print("Syncing session statuses...")
    updated = sync_session_statuses()
    if updated:
        for u in updated:
            print(f"  {u['session_id']}: {u['old_status']} -> {u['new_status']}"
                  + (f" PR: {u['pr_url']}" if u.get("pr_url") else ""))
    else:
        print("  No sessions to update.")


def cmd_backfill(args: argparse.Namespace) -> None:
    """Fetch open #bug:cosmetic issues and create Devin sessions for unhandled ones."""
    init_db()

    from src.github_client import get_open_issues, get_open_prs, find_linked_pr
    from src.orchestrator import create_session
    from src.db import save_cosmetic_issue, get_tracked_issue_numbers

    print(f"Fetching open #bug:cosmetic issues from {SUPERSET_REPO}...")
    issues = get_open_issues("#bug:cosmetic")
    print(f"  Found {len(issues)} open issue(s).")

    if not issues:
        print("  No open #bug:cosmetic issues. Nothing to do.")
        return

    open_prs = get_open_prs()
    tracked_numbers = get_tracked_issue_numbers()

    new_issues = []
    for issue in issues:
        if issue.number in tracked_numbers:
            print(f"  Issue #{issue.number} already tracked. Skipping.")
            continue
        linked_pr = find_linked_pr(issue.number, issue.title, open_prs)
        if linked_pr:
            print(f"  Issue #{issue.number} already has a linked PR (#{linked_pr.number}). Recording and skipping.")
            save_cosmetic_issue(
                issue_number=issue.number,
                title=issue.title,
                url=issue.url,
                status="has_pr",
            )
            continue
        new_issues.append(issue)

    if not new_issues:
        print("\n  All issues already have associated sessions or PRs. Nothing to backfill.")
        return

    if not DEVIN_API_TOKEN:
        print("\n[ERROR] DEVIN_API_TOKEN not set. Cannot create Devin sessions.")
        sys.exit(1)

    print(f"\n  Creating Devin sessions for {len(new_issues)} new issue(s)...")
    for issue in new_issues:
        prompt = f"""Fix cosmetic bug in Apache Superset ({SUPERSET_REPO}).

GitHub Issue: {issue.url}
Title: {issue.title}

Instructions:
1. Read the issue description carefully
2. Identify the affected component(s)
3. Implement a minimal CSS/styling fix
4. Create a PR referencing the issue: Fixes #{issue.number}

Target branch: master
"""
        tags = ["bug-cosmetic", f"issue:{issue.number}"]

        try:
            result = create_session(prompt, tags=tags)
            session_id = result.get("session_id", "")
            session_url = result.get("url", f"https://app.devin.ai/sessions/{session_id}")

            save_cosmetic_issue(
                issue_number=issue.number,
                title=issue.title,
                url=issue.url,
                status="session_created",
                session_id=session_id,
                session_url=session_url,
            )
            print(f"    Issue #{issue.number}: session created -> {session_url}")
        except Exception as e:
            print(f"    [ERROR] Issue #{issue.number}: {e}")


def cmd_verify(args: argparse.Namespace) -> None:
    """Create Playwright verification sessions for unverified PRs."""
    init_db()

    from src.github_client import get_open_prs, get_pr_comments
    from src.db import get_verified_pr_numbers, mark_pr_verified

    print(f"Checking open PRs in {SUPERSET_REPO} for verification...")
    open_prs = get_open_prs()

    # Filter to cosmetic bug fix PRs (branch starts with devin/ and title contains fix)
    cosmetic_prs = [
        pr for pr in open_prs
        if pr.head_branch.startswith("devin/") and
        any(kw in pr.title.lower() for kw in ["fix(ui)", "cosmetic", "overflow", "outline", "dropdown", "width"])
    ]

    if not cosmetic_prs:
        print("  No cosmetic fix PRs found to verify.")
        return

    verified_numbers = get_verified_pr_numbers()
    unverified = [pr for pr in cosmetic_prs if pr.number not in verified_numbers]

    if not unverified:
        print("  All cosmetic PRs already verified. Nothing to do.")
        return

    print(f"  Found {len(unverified)} unverified PR(s).")

    if not DEVIN_API_TOKEN:
        print("\n[ERROR] DEVIN_API_TOKEN not set. Cannot create verification session.")
        sys.exit(1)

    # Create a single verification session for all unverified PRs
    pr_details = "\n".join(
        f"- PR #{pr.number}: {pr.title} ({pr.url})" for pr in unverified
    )
    prompt = f"""Visually verify cosmetic bug fix PRs in Apache Superset ({SUPERSET_REPO}) using Playwright.

PRs to verify:
{pr_details}

Instructions:
1. For each PR, check out the branch and render the affected component in isolation using Playwright
2. Also render the component on the base branch (master) for comparison
3. Capture before/after screenshots
4. Post the screenshots as a comment on each PR with a visual diff summary
5. Focus on the specific UI element mentioned in the PR title

Use Playwright with headless Chrome to render components.
"""
    tags = ["verification", "playwright", "cosmetic-bugs"]

    try:
        from src.orchestrator import create_session

        result = create_session(prompt, tags=tags)
        session_id = result.get("session_id", "")
        session_url = result.get("url", f"https://app.devin.ai/sessions/{session_id}")

        for pr in unverified:
            mark_pr_verified(pr.number, session_id=session_id, session_url=session_url)

        print(f"  Verification session created: {session_url}")
        print(f"  Covering {len(unverified)} PR(s).")
    except Exception as e:
        print(f"  [ERROR] Failed to create verification session: {e}")


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the webhook server."""
    from src.webhook import create_app

    app = create_app()
    print(f"Starting webhook server on port {args.port}...")
    print(f"  Webhook endpoint: http://localhost:{args.port}/webhook")
    print(f"  Report endpoint:  http://localhost:{args.port}/report")
    print(f"  Text report:      http://localhost:{args.port}/report/text")
    print(f"  Health check:     http://localhost:{args.port}/health")
    app.run(host="0.0.0.0", port=args.port, debug=args.debug)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Superset i18n Coverage Automation",
        prog="python -m src.cli",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Run an i18n coverage scan")
    scan_parser.add_argument("--fix", action="store_true",
                             help="Create Devin sessions to fix gaps")
    scan_parser.add_argument("--dry-run", action="store_true",
                             help="Show what would be done without creating sessions")
    scan_parser.add_argument("--threshold", type=float,
                             help=f"Coverage threshold (default: {COVERAGE_THRESHOLD})")
    scan_parser.add_argument("--fresh", action="store_true",
                             help="Force a fresh clone of the repo")
    scan_parser.set_defaults(func=cmd_scan)

    report_parser = subparsers.add_parser("report", help="Show observability report")
    report_parser.set_defaults(func=cmd_report)

    sync_parser = subparsers.add_parser("sync", help="Sync session statuses from Devin API")
    sync_parser.set_defaults(func=cmd_sync)

    backfill_parser = subparsers.add_parser("backfill", help="Backfill Devin sessions for open #bug:cosmetic issues")
    backfill_parser.set_defaults(func=cmd_backfill)

    verify_parser = subparsers.add_parser("verify", help="Create Playwright verification for unverified PRs")
    verify_parser.set_defaults(func=cmd_verify)

    serve_parser = subparsers.add_parser("serve", help="Start the webhook server")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--debug", action="store_true")
    serve_parser.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
