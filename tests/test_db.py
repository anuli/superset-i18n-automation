"""Tests for the database module."""

import os
import tempfile

import pytest

from src.scanner import LocaleCoverage, ScanResult


@pytest.fixture(autouse=True)
def _use_temp_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use a temporary database for each test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        monkeypatch.setattr("src.config.DB_PATH", f.name)
        monkeypatch.setattr("src.db.DB_PATH", f.name)
        yield
        os.unlink(f.name)


def test_init_and_save_scan() -> None:
    from src.db import get_latest_scan, init_db, save_scan

    init_db()

    result = ScanResult(
        locale_coverages=[
            LocaleCoverage("de", 100, 90, 10, 0, 90.0),
            LocaleCoverage("fr", 100, 70, 30, 5, 70.0),
        ],
        unwrapped_strings=[],
        pot_total_strings=100,
        commit_sha="abc123",
        repo="anuli/superset",
        branch="master",
    )

    scan_id = save_scan(result, trigger_type="test")
    assert scan_id > 0

    latest = get_latest_scan()
    assert latest is not None
    assert latest["commit_sha"] == "abc123"
    assert latest["pot_total_strings"] == 100
    assert len(latest["locale_coverages"]) == 2


def test_save_and_update_session() -> None:
    from src.db import get_all_sessions, init_db, save_scan, save_session, update_session_status

    init_db()

    result = ScanResult(
        locale_coverages=[],
        unwrapped_strings=[],
        pot_total_strings=50,
        commit_sha="def456",
        repo="anuli/superset",
        branch="master",
    )
    scan_id = save_scan(result)

    save_session(
        scan_id=scan_id,
        session_id="session-123",
        session_url="https://app.devin.ai/sessions/session-123",
        locale="de",
        task_type="locale_translation",
        prompt="Fix de translations",
    )

    sessions = get_all_sessions(scan_id)
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "session-123"
    assert sessions[0]["status"] == "created"

    update_session_status("session-123", "finished", "https://github.com/anuli/superset/pull/1")

    sessions = get_all_sessions(scan_id)
    assert sessions[0]["status"] == "finished"
    assert sessions[0]["pr_url"] == "https://github.com/anuli/superset/pull/1"


def test_session_stats() -> None:
    from src.db import get_session_stats, init_db, save_scan, save_session, update_session_status

    init_db()

    result = ScanResult(
        locale_coverages=[],
        unwrapped_strings=[],
        pot_total_strings=50,
        commit_sha="ghi789",
        repo="anuli/superset",
        branch="master",
    )
    scan_id = save_scan(result)

    save_session(scan_id, "s1", "url1", "de", "locale_translation", "p1")
    save_session(scan_id, "s2", "url2", "fr", "locale_translation", "p2")
    save_session(scan_id, "s3", "url3", None, "unwrapped_strings", "p3")

    update_session_status("s1", "finished", "https://github.com/pr/1")
    update_session_status("s2", "error")

    stats = get_session_stats()
    assert stats["total_sessions"] == 3
    assert stats["sessions_with_prs"] == 1
    assert stats["by_status"]["finished"] == 1
    assert stats["by_status"]["error"] == 1
    assert stats["by_status"]["created"] == 1


def test_scan_history() -> None:
    from src.db import get_scan_history, init_db, save_scan

    init_db()

    for i in range(3):
        result = ScanResult(
            locale_coverages=[],
            unwrapped_strings=[],
            pot_total_strings=50 + i,
            commit_sha=f"sha{i}",
            repo="anuli/superset",
            branch="master",
        )
        save_scan(result, trigger_type=f"test-{i}")

    history = get_scan_history(limit=5)
    assert len(history) == 3
    assert history[0]["commit_sha"] == "sha2"
