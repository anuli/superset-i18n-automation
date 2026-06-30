"""Tests for the database module."""

import os
import tempfile

import pytest

from src.db import (
    get_all_sessions,
    get_issue_by_number,
    get_recent_events,
    get_session_stats,
    get_sessions_for_issue,
    init_db,
    log_event,
    save_issue,
    save_session,
    update_session_status,
)


@pytest.fixture(autouse=True)
def _use_temp_db(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        monkeypatch.setattr("src.config.DB_PATH", f.name)
        monkeypatch.setattr("src.db.DB_PATH", f.name)
        yield
        os.unlink(f.name)


def test_init_and_save_issue() -> None:
    init_db()
    issue_id = save_issue(
        issue_number=42,
        issue_url="https://github.com/anuli/superset/issues/42",
        title="Button text overflow",
        body="The button overflows on mobile.",
        labels=["#bug:cosmetic"],
    )
    assert issue_id > 0

    issue = get_issue_by_number(42)
    assert issue is not None
    assert issue["title"] == "Button text overflow"


def test_save_issue_upserts() -> None:
    init_db()
    id1 = save_issue(42, "url", "Title A", None, ["#bug:cosmetic"])
    id2 = save_issue(42, "url", "Title B", None, ["#bug:cosmetic"])
    assert id1 == id2
    issue = get_issue_by_number(42)
    assert issue["title"] == "Title B"


def test_save_and_update_session() -> None:
    init_db()
    issue_id = save_issue(1, "url1", "title", None, ["#bug:cosmetic"])
    save_session(issue_id, "sess-1", "https://devin/sess-1", "fix it")

    sessions = get_sessions_for_issue(1)
    assert len(sessions) == 1
    assert sessions[0]["status"] == "created"

    update_session_status("sess-1", "finished", "https://github.com/pr/1")
    sessions = get_sessions_for_issue(1)
    assert sessions[0]["status"] == "finished"
    assert sessions[0]["pr_url"] == "https://github.com/pr/1"


def test_session_stats() -> None:
    init_db()
    id1 = save_issue(1, "u1", "t1", None, ["#bug:cosmetic"])
    id2 = save_issue(2, "u2", "t2", None, ["#bug:cosmetic"])

    save_session(id1, "s1", "url1", "p1")
    save_session(id1, "s2", "url2", "p2")
    save_session(id2, "s3", "url3", "p3")

    update_session_status("s1", "finished", "https://github.com/pr/1")
    update_session_status("s2", "error")

    stats = get_session_stats()
    assert stats["total_sessions"] == 3
    assert stats["total_issues_tracked"] == 2
    assert stats["sessions_with_prs"] == 1
    assert stats["by_status"]["finished"] == 1
    assert stats["by_status"]["error"] == 1
    assert stats["by_status"]["created"] == 1


def test_log_and_get_events() -> None:
    init_db()
    log_event("issue_received", issue_number=42)
    log_event("session_created", issue_number=42, session_id="s1",
              details={"prompt_len": 500})

    events = get_recent_events(limit=10)
    assert len(events) == 2
    assert events[0]["event_type"] == "session_created"
    assert events[0]["details"]["prompt_len"] == 500


def test_get_all_sessions_includes_issue_info() -> None:
    init_db()
    issue_id = save_issue(99, "url", "Dark mode button", None, ["#bug:cosmetic"])
    save_session(issue_id, "sx", "urlx", "prompt")

    sessions = get_all_sessions()
    assert len(sessions) == 1
    assert sessions[0]["github_issue_number"] == 99
    assert sessions[0]["issue_title"] == "Dark mode button"
