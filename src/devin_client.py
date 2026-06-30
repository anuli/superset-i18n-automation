"""
Client for the Devin REST API.

Handles session creation and status polling.
"""

import requests

from src.config import DEVIN_API_BASE, DEVIN_API_TOKEN


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {DEVIN_API_TOKEN}",
        "Content-Type": "application/json",
    }


def create_session(prompt: str, tags: list[str] | None = None) -> dict:
    """Create a new Devin session.

    Returns the API response containing session_id and url.
    """
    payload: dict = {"prompt": prompt}
    if tags:
        payload["tags"] = tags

    resp = requests.post(
        f"{DEVIN_API_BASE}/sessions",
        headers=_headers(),
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_session(session_id: str) -> dict:
    """Retrieve current status of a Devin session."""
    resp = requests.get(
        f"{DEVIN_API_BASE}/sessions/{session_id}",
        headers=_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
