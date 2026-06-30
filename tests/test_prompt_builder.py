"""Tests for prompt_builder."""

from src.prompt_builder import (
    build_cosmetic_fix_prompt,
    build_screenshot_verification_prompt,
)


def test_prompt_contains_issue_number() -> None:
    prompt = build_cosmetic_fix_prompt(42, "Button overflow", "Details here")
    assert "#42" in prompt
    assert "Button overflow" in prompt
    assert "Details here" in prompt


def test_prompt_handles_none_body() -> None:
    prompt = build_cosmetic_fix_prompt(1, "Title", None)
    assert "#1" in prompt
    assert "no additional details" in prompt


def test_prompt_mentions_repo() -> None:
    prompt = build_cosmetic_fix_prompt(10, "Dark mode", "body")
    assert "anuli/superset" in prompt


def test_prompt_includes_verification_pending_note() -> None:
    prompt = build_cosmetic_fix_prompt(5, "Overflow bug", "body")
    assert "Pending" in prompt
    assert "Playwright verification session" in prompt


def test_verification_prompt_lists_all_prs() -> None:
    entries = [
        {"issue_number": 5, "title": "Overflow", "body": "text overflows",
         "pr_url": "https://github.com/anuli/superset/pull/10",
         "pr_number": "10", "branch": "devin/fix-issue-5"},
        {"issue_number": 6, "title": "Timestamp", "body": "timestamps clip",
         "pr_url": "https://github.com/anuli/superset/pull/11",
         "pr_number": "11", "branch": "devin/fix-issue-6"},
    ]
    prompt = build_screenshot_verification_prompt(entries)
    assert "PR #10" in prompt
    assert "PR #11" in prompt
    assert "devin/fix-issue-5" in prompt
    assert "devin/fix-issue-6" in prompt
    assert "Playwright" in prompt
    assert "npm install" in prompt
    assert "text overflows" in prompt


def test_verification_prompt_empty() -> None:
    assert build_screenshot_verification_prompt([]) == ""


def test_verification_prompt_fallback_handling() -> None:
    entries = [{"issue_number": 1, "title": "T", "body": "desc",
                "pr_url": "url", "pr_number": "1", "branch": "b"}]
    prompt = build_screenshot_verification_prompt(entries)
    assert "cannot render" in prompt.lower() or "could not be rendered" in prompt.lower()
    assert "code review" in prompt.lower()
