"""Tests for the i18n scanner module."""

import tempfile
from pathlib import Path

from src.scanner import (
    LocaleCoverage,
    UnwrappedString,
    count_pot_strings,
    parse_po_file,
    scan_unwrapped_strings,
)


def _write_po_file(tmp: Path, locale: str, entries: list[tuple[str, str]]) -> Path:
    """Create a minimal .po file for testing."""
    po_dir = tmp / locale / "LC_MESSAGES"
    po_dir.mkdir(parents=True)
    po_path = po_dir / "messages.po"

    lines = [
        'msgid ""',
        'msgstr ""',
        '"Content-Type: text/plain; charset=utf-8\\n"',
        "",
    ]
    for msgid, msgstr in entries:
        lines.extend([f'msgid "{msgid}"', f'msgstr "{msgstr}"', ""])

    po_path.write_text("\n".join(lines), encoding="utf-8")
    return po_path


def test_parse_po_file_full_coverage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        po_path = _write_po_file(Path(tmp), "de", [
            ("Hello", "Hallo"),
            ("Save", "Speichern"),
            ("Cancel", "Abbrechen"),
        ])
        result = parse_po_file(po_path)
        assert result.locale == "de"
        assert result.total_strings == 3
        assert result.translated == 3
        assert result.untranslated == 0
        assert result.coverage_pct == 100.0


def test_parse_po_file_partial_coverage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        po_path = _write_po_file(Path(tmp), "fr", [
            ("Hello", "Bonjour"),
            ("Save", ""),
            ("Cancel", "Annuler"),
            ("Delete", ""),
        ])
        result = parse_po_file(po_path)
        assert result.locale == "fr"
        assert result.total_strings == 4
        assert result.translated == 2
        assert result.untranslated == 2
        assert result.coverage_pct == 50.0


def test_parse_po_file_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        po_path = _write_po_file(Path(tmp), "ko", [])
        result = parse_po_file(po_path)
        assert result.total_strings == 0
        assert result.coverage_pct == 0.0


def test_count_pot_strings() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        pot_path = Path(tmp) / "messages.pot"
        pot_path.write_text(
            'msgid ""\nmsgstr ""\n\nmsgid "Hello"\nmsgstr ""\n\n'
            'msgid "Save"\nmsgstr ""\n\nmsgid "Cancel"\nmsgstr ""\n',
            encoding="utf-8",
        )
        assert count_pot_strings(pot_path) == 3


def test_scan_unwrapped_strings() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp)
        src_dir = repo_dir / "superset-frontend" / "src" / "components"
        src_dir.mkdir(parents=True)

        (src_dir / "MyComponent.tsx").write_text(
            'import React from "react";\n'
            '\n'
            'const MyComponent = () => (\n'
            '  <div title="Dashboard Overview">\n'
            '    <button label={t("Save")}>Click</button>\n'
            '    <input placeholder="Search charts" />\n'
            '  </div>\n'
            ');\n',
            encoding="utf-8",
        )

        results = scan_unwrapped_strings(repo_dir)
        string_values = [r.string_value for r in results]
        assert "Dashboard Overview" in string_values
        assert "Search charts" in string_values
        assert "Save" not in string_values


def test_scan_ignores_test_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp)
        src_dir = repo_dir / "superset-frontend" / "src" / "components"
        src_dir.mkdir(parents=True)

        (src_dir / "MyComponent.test.tsx").write_text(
            'const wrapper = render(<Comp title="Test Title" />);\n',
            encoding="utf-8",
        )

        results = scan_unwrapped_strings(repo_dir)
        assert len(results) == 0
