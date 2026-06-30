"""Tests for the orchestrator module."""

import os
import tempfile
from unittest.mock import patch

import pytest

from src.db import get_sessions_for_issue, init_db, save_issue, save_session
from src.orchestrator import handle_issue, sync_session_statuses


@pytest.fixture(autouse=True)
def _use_temp_db(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        monkeypatch.setattr("src.config.DB_PATH", f.name)
        monkeypatch.setattr("src.db.DB_PATH", f.name)
        yield
        os.unlink(f.name)


@patch("src.orchestrator.devin_client.create_session")
def test_handle_issue_creates_session(mock_create) -> None:
    init_db()
    mock_create.return_value = {
        "session_id": "abc123",
        "url": "https://app.devin.ai/sessions/abc123",
    }

    result = handle_issue(
        issue_number=42,
        issue_url="https://github.com/anuli/superset/issues/42",
        title="Button overflow",
        body="It overflows on mobile.",
        labels=["#bug:cosmetic"],
    )

    assert result["session_id"] == "abc123"
    mock_create.assert_called_once()


def test_handle_issue_skips_without_label() -> None:
    init_db()
    result = handle_issue(
        issue_number=1,
        issue_url="url",
        title="Not cosmetic",
        body="body",
        labels=["enhancement"],
    )
    assert result["skipped"] is True
    assert "label" in result["reason"]


@patch("src.orchestrator.devin_client.create_session")
def test_handle_issue_skips_duplicate(mock_create) -> None:
    init_db()
    mock_create.return_value = {"session_id": "s1", "url": "u1"}

    handle_issue(10, "url", "Title", "Body", ["#bug:cosmetic"])

    result = handle_issue(10, "url", "Title", "Body", ["#bug:cosmetic"])
    assert result["skipped"] is True
    assert "already exists" in result["reason"]
    assert mock_create.call_count == 1


@patch("src.orchestrator.devin_client.get_session")
def test_sync_session_statuses(mock_get) -> None:
    init_db()
    issue_id = save_issue(5, "url", "title", None, ["#bug:cosmetic"])
    save_session(issue_id, "s-active", "url", "prompt")

    mock_get.return_value = {
        "status_enum": "finished",
        "pull_request": {"url": "https://github.com/anuli/superset/pull/99"},
    }

    updated = sync_session_statuses()
    assert len(updated) == 1
    assert updated[0]["new_status"] == "finished"
    assert updated[0]["pr_url"] == "https://github.com/anuli/superset/pull/99"
