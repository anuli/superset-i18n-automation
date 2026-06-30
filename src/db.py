"""
SQLite persistence for issues, Devin sessions, and metrics.
"""

import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Generator

from src.config import DB_PATH


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create database tables if they don't exist."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                github_issue_number INTEGER NOT NULL,
                github_issue_url TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT,
                labels_json TEXT NOT NULL DEFAULT '[]',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                session_url TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'created',
                pr_url TEXT,
                screenshot_status TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (issue_id) REFERENCES issues(id)
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,
                issue_number INTEGER,
                session_id TEXT,
                details_json TEXT
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_issues_number
                ON issues(github_issue_number);
            CREATE INDEX IF NOT EXISTS idx_sessions_status
                ON sessions(status);
            CREATE INDEX IF NOT EXISTS idx_sessions_issue
                ON sessions(issue_id);
            CREATE INDEX IF NOT EXISTS idx_events_timestamp
                ON events(timestamp);
        """)


def save_issue(
    issue_number: int,
    issue_url: str,
    title: str,
    body: str | None,
    labels: list[str],
) -> int:
    """Save or update a GitHub issue record. Returns the row ID."""
    now = time.time()
    labels_json = json.dumps(labels)
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM issues WHERE github_issue_number = ?",
            (issue_number,),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE issues
                   SET title = ?, body = ?, labels_json = ?, updated_at = ?
                   WHERE id = ?""",
                (title, body, labels_json, now, existing["id"]),
            )
            return existing["id"]
        cursor = conn.execute(
            """INSERT INTO issues
               (github_issue_number, github_issue_url, title, body,
                labels_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (issue_number, issue_url, title, body, labels_json, now, now),
        )
        return cursor.lastrowid


def save_session(
    issue_id: int,
    session_id: str,
    session_url: str,
    prompt: str,
) -> int:
    """Save a Devin session record."""
    now = time.time()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO sessions
               (issue_id, session_id, session_url, prompt,
                status, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'created', ?, ?)""",
            (issue_id, session_id, session_url, prompt, now, now),
        )
        return cursor.lastrowid


def update_session_status(
    session_id: str, status: str, pr_url: str | None = None
) -> None:
    """Update a session's status and optionally its PR URL."""
    now = time.time()
    with get_db() as conn:
        if pr_url:
            conn.execute(
                """UPDATE sessions
                   SET status = ?, pr_url = ?, updated_at = ?
                   WHERE session_id = ?""",
                (status, pr_url, now, session_id),
            )
        else:
            conn.execute(
                """UPDATE sessions
                   SET status = ?, updated_at = ?
                   WHERE session_id = ?""",
                (status, now, session_id),
            )


def log_event(
    event_type: str,
    issue_number: int | None = None,
    session_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Record an event for the audit log."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO events (timestamp, event_type, issue_number,
               session_id, details_json)
               VALUES (?, ?, ?, ?, ?)""",
            (time.time(), event_type, issue_number, session_id,
             json.dumps(details) if details else None),
        )


def get_issue_by_number(issue_number: int) -> dict | None:
    """Look up an issue by its GitHub number."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM issues WHERE github_issue_number = ?",
            (issue_number,),
        ).fetchone()
    return dict(row) if row else None


def get_sessions_for_issue(issue_number: int) -> list[dict]:
    """Get all sessions associated with an issue."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT s.* FROM sessions s
               JOIN issues i ON s.issue_id = i.id
               WHERE i.github_issue_number = ?
               ORDER BY s.created_at DESC""",
            (issue_number,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_sessions() -> list[dict]:
    """Get all sessions ordered by creation time."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT s.*, i.github_issue_number, i.title as issue_title
               FROM sessions s
               JOIN issues i ON s.issue_id = i.id
               ORDER BY s.created_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_active_sessions() -> list[dict]:
    """Get sessions that are still running."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT s.*, i.github_issue_number, i.title as issue_title
               FROM sessions s
               JOIN issues i ON s.issue_id = i.id
               WHERE s.status NOT IN ('finished', 'stopped', 'error')
               ORDER BY s.created_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_session_stats() -> dict:
    """Get aggregate session statistics including timing and verification."""
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        by_status = conn.execute(
            "SELECT status, COUNT(*) as count FROM sessions GROUP BY status"
        ).fetchall()
        with_prs = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE pr_url IS NOT NULL"
        ).fetchone()[0]
        total_issues = conn.execute(
            "SELECT COUNT(*) FROM issues"
        ).fetchone()[0]

        # Verification stats
        verified = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE screenshot_status = 'done'"
        ).fetchone()[0]
        verify_in_progress = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE screenshot_status = 'in_progress'"
        ).fetchone()[0]
        verify_errors = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE screenshot_status = 'error'"
        ).fetchone()[0]
        verify_pending = conn.execute(
            """SELECT COUNT(*) FROM sessions
               WHERE pr_url IS NOT NULL AND screenshot_status IS NULL"""
        ).fetchone()[0]

        # Timing: average time from session creation to PR (finished sessions)
        avg_time_row = conn.execute(
            """SELECT AVG(s.updated_at - s.created_at) as avg_seconds
               FROM sessions s
               WHERE s.status = 'finished' AND s.pr_url IS NOT NULL"""
        ).fetchone()
        avg_time_to_pr = avg_time_row["avg_seconds"] if avg_time_row else None

        # Throughput: sessions created in last 24h and last 7d
        now = time.time()
        last_24h = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE created_at > ?",
            (now - 86400,),
        ).fetchone()[0]
        last_7d = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE created_at > ?",
            (now - 604800,),
        ).fetchone()[0]
        prs_last_24h = conn.execute(
            """SELECT COUNT(*) FROM sessions
               WHERE pr_url IS NOT NULL AND updated_at > ?""",
            (now - 86400,),
        ).fetchone()[0]
        prs_last_7d = conn.execute(
            """SELECT COUNT(*) FROM sessions
               WHERE pr_url IS NOT NULL AND updated_at > ?""",
            (now - 604800,),
        ).fetchone()[0]

    return {
        "total_sessions": total,
        "total_issues_tracked": total_issues,
        "by_status": {row["status"]: row["count"] for row in by_status},
        "sessions_with_prs": with_prs,
        "verification": {
            "verified": verified,
            "in_progress": verify_in_progress,
            "errors": verify_errors,
            "pending": verify_pending,
        },
        "avg_time_to_pr_seconds": avg_time_to_pr,
        "throughput": {
            "sessions_last_24h": last_24h,
            "sessions_last_7d": last_7d,
            "prs_last_24h": prs_last_24h,
            "prs_last_7d": prs_last_7d,
        },
    }


def get_sessions_needing_screenshots() -> list[dict]:
    """Get sessions that have PRs but haven't been screenshot-verified yet."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT s.*, i.github_issue_number, i.title as issue_title,
                      i.body as issue_body
               FROM sessions s
               JOIN issues i ON s.issue_id = i.id
               WHERE s.pr_url IS NOT NULL
                 AND s.screenshot_status IS NULL
               ORDER BY s.created_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def update_screenshot_status(session_id: str, status: str) -> None:
    """Mark a session's screenshot verification status."""
    now = time.time()
    with get_db() as conn:
        conn.execute(
            """UPDATE sessions
               SET screenshot_status = ?, updated_at = ?
               WHERE session_id = ?""",
            (status, now, session_id),
        )


def get_recent_events(limit: int = 50) -> list[dict]:
    """Get the most recent events."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        if d.get("details_json"):
            d["details"] = json.loads(d["details_json"])
        else:
            d["details"] = None
        del d["details_json"]
        results.append(d)
    return results
