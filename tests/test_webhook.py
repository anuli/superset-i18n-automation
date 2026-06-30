"""Tests for the webhook server."""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from src.webhook import app


@pytest.fixture(autouse=True)
def _use_temp_db(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        monkeypatch.setattr("src.config.DB_PATH", f.name)
        monkeypatch.setattr("src.db.DB_PATH", f.name)
        yield
        os.unlink(f.name)


@pytest.fixture
def client():
    from src.db import init_db

    init_db()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_health(client) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_ping(client) -> None:
    resp = client.post(
        "/webhook",
        data="{}",
        content_type="application/json",
        headers={"X-GitHub-Event": "ping"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["message"] == "pong"


def test_ignores_non_issue_event(client) -> None:
    resp = client.post(
        "/webhook",
        data=json.dumps({"action": "opened"}),
        content_type="application/json",
        headers={"X-GitHub-Event": "push"},
    )
    assert resp.status_code == 200
    assert "Ignored" in resp.get_json()["message"]


def test_ignores_irrelevant_action(client) -> None:
    resp = client.post(
        "/webhook",
        data=json.dumps({"action": "closed", "issue": {}}),
        content_type="application/json",
        headers={"X-GitHub-Event": "issues"},
    )
    assert resp.status_code == 200
    assert "Ignored action" in resp.get_json()["message"]


def test_ignores_wrong_label(client) -> None:
    resp = client.post(
        "/webhook",
        data=json.dumps({
            "action": "labeled",
            "label": {"name": "enhancement"},
            "issue": {
                "number": 1,
                "labels": [{"name": "enhancement"}],
            },
            "repository": {"full_name": "anuli/superset"},
        }),
        content_type="application/json",
        headers={"X-GitHub-Event": "issues"},
    )
    assert resp.status_code == 200
    assert "Ignored label" in resp.get_json()["message"]


def test_ignores_wrong_repo(client) -> None:
    resp = client.post(
        "/webhook",
        data=json.dumps({
            "action": "labeled",
            "label": {"name": "#bug:cosmetic"},
            "issue": {
                "number": 1,
                "labels": [{"name": "#bug:cosmetic"}],
            },
            "repository": {"full_name": "other/repo"},
        }),
        content_type="application/json",
        headers={"X-GitHub-Event": "issues"},
    )
    assert resp.status_code == 200
    assert "Ignored repo" in resp.get_json()["message"]


@patch("src.orchestrator.devin_client.create_session")
def test_webhook_creates_session(mock_create, client) -> None:
    mock_create.return_value = {
        "session_id": "test-session-123",
        "url": "https://app.devin.ai/sessions/test-session-123",
    }
    resp = client.post(
        "/webhook",
        data=json.dumps({
            "action": "labeled",
            "label": {"name": "#bug:cosmetic"},
            "issue": {
                "number": 42,
                "html_url": "https://github.com/anuli/superset/issues/42",
                "title": "Button overflow on mobile",
                "body": "The save button overflows.",
                "labels": [{"name": "#bug:cosmetic"}],
            },
            "repository": {"full_name": "anuli/superset"},
        }),
        content_type="application/json",
        headers={"X-GitHub-Event": "issues"},
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["session_id"] == "test-session-123"
    mock_create.assert_called_once()


@patch("src.orchestrator.devin_client.create_session")
def test_webhook_opened_with_label(mock_create, client) -> None:
    mock_create.return_value = {
        "session_id": "s-opened",
        "url": "https://app.devin.ai/sessions/s-opened",
    }
    resp = client.post(
        "/webhook",
        data=json.dumps({
            "action": "opened",
            "issue": {
                "number": 10,
                "html_url": "https://github.com/anuli/superset/issues/10",
                "title": "Dark mode colors",
                "body": "Colors look wrong.",
                "labels": [{"name": "#bug:cosmetic"}],
            },
            "repository": {"full_name": "anuli/superset"},
        }),
        content_type="application/json",
        headers={"X-GitHub-Event": "issues"},
    )
    assert resp.status_code == 201
    assert resp.get_json()["session_id"] == "s-opened"


def test_report_empty(client) -> None:
    resp = client.get("/report")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "generated_at" in data
    assert data["stats"]["total_sessions"] == 0


def test_report_text_empty(client) -> None:
    resp = client.get("/report/text")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Automation Report" in body
    assert "Issues tracked" in body
    assert "Success rate" in body
