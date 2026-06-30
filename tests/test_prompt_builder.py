"""Tests for prompt_builder."""

from src.prompt_builder import build_cosmetic_fix_prompt


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
