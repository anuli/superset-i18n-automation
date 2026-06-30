"""
Devin API orchestrator for creating and managing i18n fix sessions.
"""

import time

import requests

from src.config import DEVIN_API_BASE, DEVIN_API_TOKEN, SUPERSET_REPO
from src.db import save_session, update_session_status
from src.scanner import LocaleCoverage, ScanResult


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {DEVIN_API_TOKEN}",
        "Content-Type": "application/json",
    }


def _build_locale_fix_prompt(locale: str, coverage: LocaleCoverage) -> str:
    """Build a prompt for Devin to fix a locale's translation gaps."""
    return f"""Fix missing translations for the '{locale}' locale in the Apache Superset repo ({SUPERSET_REPO}).

The locale file is at: superset/translations/{locale}/LC_MESSAGES/messages.po
The template file (source of truth) is at: superset/translations/messages.pot

Current status:
- Total strings: {coverage.total_strings}
- Translated: {coverage.translated}
- Untranslated: {coverage.untranslated}
- Coverage: {coverage.coverage_pct}%

Instructions:
1. Open the .po file for this locale
2. Find entries where msgstr is empty ("")
3. Provide accurate translations for the empty msgstr entries
4. Focus on the most user-visible strings first (UI labels, button text, error messages)
5. Translate up to 50 strings per session to keep PRs reviewable
6. Preserve all .po file formatting (comments, flags, line breaks)
7. Do NOT use machine translation placeholders — provide natural, contextually appropriate translations
8. Create a PR with the title: fix(i18n): add missing {locale} translations

Target branch: master
"""


def _build_unwrapped_strings_prompt(file_groups: dict[str, list]) -> str:
    """Build a prompt for Devin to wrap strings in t() calls."""
    file_list = "\n".join(
        f"- {f} ({len(strings)} strings)" for f, strings in file_groups.items()
    )
    sample_files = list(file_groups.keys())[:5]
    sample_details = ""
    for f in sample_files:
        strings = file_groups[f][:3]
        for s in strings:
            sample_details += f"  Line {s['line_number']}: {s['line_content'][:120]}\n"

    return f"""Wrap untranslated UI strings in t() calls in the Apache Superset frontend ({SUPERSET_REPO}).

Files with unwrapped strings:
{file_list}

Sample locations:
{sample_details}

Instructions:
1. Import t from '@apache-superset/core/translation' if not already imported
2. Wrap user-visible string literals in t() calls
3. Only wrap strings that are displayed to users (labels, titles, placeholders, error messages)
4. Do NOT wrap: CSS class names, HTML attributes, test IDs, data keys, URLs, variable names
5. Keep changes minimal and focused — only add t() wrappers
6. Create a PR with the title: fix(i18n): wrap untranslated frontend strings in t()

Target branch: master
"""


def create_session(prompt: str, tags: list[str] | None = None) -> dict:
    """Create a new Devin session via the API."""
    payload: dict = {
        "prompt": prompt,
    }
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


def get_session_status(session_id: str) -> dict:
    """Get the current status of a Devin session."""
    resp = requests.get(
        f"{DEVIN_API_BASE}/sessions/{session_id}",
        headers=_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def poll_session(session_id: str, interval: int = 30, timeout: int = 1800) -> dict:
    """Poll a session until it completes or times out."""
    start = time.time()
    while time.time() - start < timeout:
        status = get_session_status(session_id)
        current = status.get("status_enum", status.get("status", ""))
        if current in ("finished", "stopped", "error", "blocked"):
            return status
        time.sleep(interval)
    return get_session_status(session_id)


def create_locale_fix_sessions(
    scan_id: int,
    scan_result: ScanResult,
    threshold: float = 80.0,
    max_sessions: int = 3,
) -> list[dict]:
    """Create Devin sessions for locales below the coverage threshold."""
    below_threshold = [
        c for c in scan_result.locale_coverages
        if c.coverage_pct < threshold
    ]
    below_threshold.sort(key=lambda c: c.coverage_pct)

    created = []
    for coverage in below_threshold[:max_sessions]:
        prompt = _build_locale_fix_prompt(coverage.locale, coverage)
        tags = ["i18n-automation", f"locale:{coverage.locale}", "translation-fix"]

        try:
            result = create_session(prompt, tags=tags)
            session_id = result.get("session_id", "")
            session_url = result.get("url", f"https://app.devin.ai/sessions/{session_id}")

            save_session(
                scan_id=scan_id,
                session_id=session_id,
                session_url=session_url,
                locale=coverage.locale,
                task_type="locale_translation",
                prompt=prompt,
            )

            created.append({
                "session_id": session_id,
                "session_url": session_url,
                "locale": coverage.locale,
                "coverage_pct": coverage.coverage_pct,
            })
        except requests.RequestException as e:
            print(f"[ERROR] Failed to create session for {coverage.locale}: {e}")

    return created


def create_unwrapped_fix_session(
    scan_id: int,
    scan_result: ScanResult,
    max_files: int = 10,
) -> dict | None:
    """Create a Devin session to fix unwrapped frontend strings."""
    if not scan_result.unwrapped_strings:
        return None

    file_groups: dict[str, list] = {}
    for s in scan_result.unwrapped_strings:
        file_groups.setdefault(s.file_path, []).append({
            "line_number": s.line_number,
            "line_content": s.line_content,
            "string_value": s.string_value,
        })

    limited_groups = dict(list(file_groups.items())[:max_files])
    prompt = _build_unwrapped_strings_prompt(limited_groups)
    tags = ["i18n-automation", "unwrapped-strings", "frontend-fix"]

    try:
        result = create_session(prompt, tags=tags)
        session_id = result.get("session_id", "")
        session_url = result.get("url", f"https://app.devin.ai/sessions/{session_id}")

        save_session(
            scan_id=scan_id,
            session_id=session_id,
            session_url=session_url,
            locale=None,
            task_type="unwrapped_strings",
            prompt=prompt,
        )

        return {
            "session_id": session_id,
            "session_url": session_url,
            "files_count": len(limited_groups),
            "strings_count": sum(len(v) for v in limited_groups.values()),
        }
    except requests.RequestException as e:
        print(f"[ERROR] Failed to create unwrapped-strings session: {e}")
        return None


def sync_session_statuses() -> list[dict]:
    """Check and update statuses for all active sessions."""
    from src.db import get_all_sessions

    active_sessions = [
        s for s in get_all_sessions()
        if s["status"] not in ("finished", "stopped", "error")
    ]

    updated = []
    for session in active_sessions:
        try:
            status = get_session_status(session["session_id"])
            new_status = status.get("status_enum", status.get("status", "unknown"))

            pr_url = None
            pull_request = status.get("pull_request")
            if pull_request:
                pr_url = pull_request.get("url")

            update_session_status(session["session_id"], new_status, pr_url)
            updated.append({
                "session_id": session["session_id"],
                "old_status": session["status"],
                "new_status": new_status,
                "pr_url": pr_url,
            })
        except requests.RequestException as e:
            print(f"[WARN] Could not check session {session['session_id']}: {e}")

    return updated
