"""
SQLite persistence for scan results, sessions, and metrics.
"""

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Generator

from src.config import DB_PATH
from src.scanner import LocaleCoverage, ScanResult, UnwrappedString


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
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                commit_sha TEXT NOT NULL,
                repo TEXT NOT NULL,
                branch TEXT NOT NULL,
                pot_total_strings INTEGER NOT NULL,
                locale_coverages_json TEXT NOT NULL,
                unwrapped_count INTEGER NOT NULL,
                trigger_type TEXT NOT NULL DEFAULT 'manual'
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                session_url TEXT NOT NULL,
                locale TEXT,
                task_type TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'created',
                pr_url TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (scan_id) REFERENCES scans(id)
            );

            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL NOT NULL,
                labels_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_scans_timestamp ON scans(timestamp);
            CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
            CREATE INDEX IF NOT EXISTS idx_sessions_scan_id ON sessions(scan_id);
            CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(metric_name);
        """)


def save_scan(result: ScanResult, trigger_type: str = "manual") -> int:
    """Save a scan result and return its ID."""
    now = time.time()
    coverages_json = json.dumps([asdict(c) for c in result.locale_coverages])

    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO scans
               (timestamp, commit_sha, repo, branch, pot_total_strings,
                locale_coverages_json, unwrapped_count, trigger_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, result.commit_sha, result.repo, result.branch,
             result.pot_total_strings, coverages_json,
             len(result.unwrapped_strings), trigger_type),
        )
        scan_id = cursor.lastrowid

        for cov in result.locale_coverages:
            conn.execute(
                """INSERT INTO metrics (timestamp, metric_name, metric_value, labels_json)
                   VALUES (?, ?, ?, ?)""",
                (now, "locale_coverage_pct", cov.coverage_pct,
                 json.dumps({"locale": cov.locale})),
            )
            conn.execute(
                """INSERT INTO metrics (timestamp, metric_name, metric_value, labels_json)
                   VALUES (?, ?, ?, ?)""",
                (now, "locale_untranslated_count", cov.untranslated,
                 json.dumps({"locale": cov.locale})),
            )

        conn.execute(
            """INSERT INTO metrics (timestamp, metric_name, metric_value, labels_json)
               VALUES (?, ?, ?, ?)""",
            (now, "unwrapped_strings_count", len(result.unwrapped_strings), None),
        )

    return scan_id


def save_session(
    scan_id: int,
    session_id: str,
    session_url: str,
    locale: str | None,
    task_type: str,
    prompt: str,
) -> int:
    """Save a Devin session record."""
    now = time.time()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO sessions
               (scan_id, session_id, session_url, locale, task_type,
                prompt, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'created', ?, ?)""",
            (scan_id, session_id, session_url, locale, task_type, prompt, now, now),
        )
        return cursor.lastrowid


def update_session_status(session_id: str, status: str, pr_url: str | None = None) -> None:
    """Update a session's status and optionally its PR URL."""
    now = time.time()
    with get_db() as conn:
        if pr_url:
            conn.execute(
                "UPDATE sessions SET status = ?, pr_url = ?, updated_at = ? WHERE session_id = ?",
                (status, pr_url, now, session_id),
            )
        else:
            conn.execute(
                "UPDATE sessions SET status = ?, updated_at = ? WHERE session_id = ?",
                (status, now, session_id),
            )


def get_latest_scan() -> dict | None:
    """Get the most recent scan result."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM scans ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if row:
            result = dict(row)
            result["locale_coverages"] = json.loads(result["locale_coverages_json"])
            return result
    return None


def get_all_sessions(scan_id: int | None = None) -> list[dict]:
    """Get all sessions, optionally filtered by scan_id."""
    with get_db() as conn:
        if scan_id:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE scan_id = ? ORDER BY created_at DESC",
                (scan_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def get_scan_history(limit: int = 20) -> list[dict]:
    """Get recent scan history."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM scans ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        d["locale_coverages"] = json.loads(d["locale_coverages_json"])
        del d["locale_coverages_json"]
        results.append(d)
    return results


def get_session_stats() -> dict:
    """Get aggregate session statistics."""
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        by_status = conn.execute(
            "SELECT status, COUNT(*) as count FROM sessions GROUP BY status"
        ).fetchall()
        with_prs = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE pr_url IS NOT NULL"
        ).fetchone()[0]

    return {
        "total_sessions": total,
        "by_status": {row["status"]: row["count"] for row in by_status},
        "sessions_with_prs": with_prs,
    }


def get_coverage_trend(locale: str, limit: int = 10) -> list[dict]:
    """Get coverage trend for a specific locale."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT timestamp, metric_value
               FROM metrics
               WHERE metric_name = 'locale_coverage_pct'
                 AND json_extract(labels_json, '$.locale') = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (locale, limit),
        ).fetchall()
    return [{"timestamp": r["timestamp"], "coverage_pct": r["metric_value"]} for r in rows]
