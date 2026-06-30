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
    data = resp.get_json()
    assert data["status"] == "ok"


def test_webhook_ignores_non_push(client) -> None:
    resp = client.post(
        "/webhook",
        data=json.dumps({"action": "opened"}),
        content_type="application/json",
        headers={"X-GitHub-Event": "pull_request"},
    )
    assert resp.status_code == 200
    assert "Ignored" in resp.get_json()["message"]


def test_webhook_ignores_wrong_branch(client) -> None:
    resp = client.post(
        "/webhook",
        data=json.dumps({
            "ref": "refs/heads/feature-branch",
            "repository": {"full_name": "anuli/superset"},
        }),
        content_type="application/json",
        headers={"X-GitHub-Event": "push"},
    )
    assert resp.status_code == 200
    assert "Ignored ref" in resp.get_json()["message"]


def test_webhook_ignores_wrong_repo(client) -> None:
    resp = client.post(
        "/webhook",
        data=json.dumps({
            "ref": "refs/heads/master",
            "repository": {"full_name": "other/repo"},
        }),
        content_type="application/json",
        headers={"X-GitHub-Event": "push"},
    )
    assert resp.status_code == 200
    assert "Ignored repo" in resp.get_json()["message"]


@patch("src.webhook._run_scan_and_fix")
def test_webhook_triggers_scan(mock_scan, client) -> None:
    resp = client.post(
        "/webhook",
        data=json.dumps({
            "ref": "refs/heads/master",
            "repository": {"full_name": "anuli/superset"},
        }),
        content_type="application/json",
        headers={"X-GitHub-Event": "push"},
    )
    assert resp.status_code == 202
    assert resp.get_json()["message"] == "Scan triggered"


def test_report_empty(client) -> None:
    resp = client.get("/report")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "generated_at" in data
    assert data["latest_scan"] is None


def test_report_text_empty(client) -> None:
    resp = client.get("/report/text")
    assert resp.status_code == 200
    assert "SUPERSET i18n AUTOMATION REPORT" in resp.data.decode()
