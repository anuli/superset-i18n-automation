"""
i18n scanner for Apache Superset.

Analyzes the superset codebase for:
1. Translation coverage per locale (.po files)
2. Frontend strings not wrapped in t() calls
"""

import os
import re
import subprocess
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from src.config import (
    FRONTEND_SRC_DIR,
    PRIORITY_LOCALES,
    SUPERSET_BRANCH,
    SUPERSET_CLONE_URL,
    TRANSLATIONS_DIR,
    WORK_DIR,
)


@dataclass
class LocaleCoverage:
    locale: str
    total_strings: int
    translated: int
    untranslated: int
    fuzzy: int
    coverage_pct: float


@dataclass
class UnwrappedString:
    file_path: str
    line_number: int
    line_content: str
    string_value: str


@dataclass
class ScanResult:
    locale_coverages: list[LocaleCoverage] = field(default_factory=list)
    unwrapped_strings: list[UnwrappedString] = field(default_factory=list)
    pot_total_strings: int = 0
    commit_sha: str = ""
    repo: str = ""
    branch: str = ""


def clone_repo(force_fresh: bool = False) -> Path:
    """Clone or update the superset repo."""
    repo_dir = WORK_DIR / "superset"

    if force_fresh and repo_dir.exists():
        shutil.rmtree(repo_dir)

    if repo_dir.exists():
        subprocess.run(
            ["git", "fetch", "origin", SUPERSET_BRANCH],
            cwd=repo_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "checkout", SUPERSET_BRANCH],
            cwd=repo_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "reset", "--hard", f"origin/{SUPERSET_BRANCH}"],
            cwd=repo_dir,
            capture_output=True,
            check=True,
        )
    else:
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth=1", "-b", SUPERSET_BRANCH, SUPERSET_CLONE_URL, str(repo_dir)],
            capture_output=True,
            check=True,
        )

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    return repo_dir


def get_commit_sha(repo_dir: Path) -> str:
    """Get the current HEAD commit SHA."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def parse_po_file(po_path: Path) -> LocaleCoverage:
    """Parse a .po file and compute translation coverage."""
    locale = po_path.parent.parent.name

    total = 0
    translated = 0
    untranslated = 0
    fuzzy_count = 0
    in_fuzzy = False
    current_msgid = []
    current_msgstr = []
    reading_msgid = False
    reading_msgstr = False
    is_header = True

    with open(po_path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()

            if line.startswith("#, fuzzy"):
                in_fuzzy = True
                continue
            if line.startswith("#"):
                continue

            if line.startswith("msgid "):
                if reading_msgstr and not is_header:
                    msgid_text = "".join(current_msgid)
                    msgstr_text = "".join(current_msgstr)
                    if msgid_text:
                        total += 1
                        if in_fuzzy:
                            fuzzy_count += 1
                        if msgstr_text:
                            translated += 1
                        else:
                            untranslated += 1

                current_msgid = [line[7:-1]]
                current_msgstr = []
                reading_msgid = True
                reading_msgstr = False
                in_fuzzy = in_fuzzy if line != 'msgid ""' else in_fuzzy
                is_header = line == 'msgid ""' and is_header

            elif line.startswith("msgstr "):
                current_msgstr = [line[8:-1]]
                reading_msgid = False
                reading_msgstr = True
                if current_msgid == [""]:
                    is_header = True
                else:
                    is_header = False

            elif line.startswith('"') and line.endswith('"'):
                content = line[1:-1]
                if reading_msgid:
                    current_msgid.append(content)
                elif reading_msgstr:
                    current_msgstr.append(content)

            elif line == "":
                if reading_msgstr and not is_header:
                    msgid_text = "".join(current_msgid)
                    msgstr_text = "".join(current_msgstr)
                    if msgid_text:
                        total += 1
                        if in_fuzzy:
                            fuzzy_count += 1
                        if msgstr_text:
                            translated += 1
                        else:
                            untranslated += 1

                current_msgid = []
                current_msgstr = []
                reading_msgid = False
                reading_msgstr = False
                in_fuzzy = False
                is_header = True

    if reading_msgstr and not is_header:
        msgid_text = "".join(current_msgid)
        msgstr_text = "".join(current_msgstr)
        if msgid_text:
            total += 1
            if in_fuzzy:
                fuzzy_count += 1
            if msgstr_text:
                translated += 1
            else:
                untranslated += 1

    coverage_pct = (translated / total * 100) if total > 0 else 0.0

    return LocaleCoverage(
        locale=locale,
        total_strings=total,
        translated=translated,
        untranslated=untranslated,
        fuzzy=fuzzy_count,
        coverage_pct=round(coverage_pct, 1),
    )


def count_pot_strings(pot_path: Path) -> int:
    """Count total msgid entries in the .pot template."""
    count = 0
    with open(pot_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("msgid ") and line.strip() != 'msgid ""':
                count += 1
    return count


_T_CALL_PATTERN = re.compile(r"""\bt\(\s*['"`]""")
_TN_CALL_PATTERN = re.compile(r"""\btn\(\s*['"`]""")

_JSX_STRING_PATTERNS = [
    re.compile(r"""(?:title|label|placeholder|description|tooltip|message|text|header|error|warning|info|name|buttonText|confirmText|cancelText)\s*=\s*["']([A-Z][^"']{2,})["']"""),
    re.compile(r"""(?:title|label|placeholder|description|tooltip|message|text|header|error|warning|info|name|buttonText|confirmText|cancelText)\s*=\s*\{?\s*["']([A-Z][^"']{2,})["']\s*\}?"""),
]

_IGNORE_PATTERNS = [
    re.compile(r"^\s*//"),
    re.compile(r"^\s*\*"),
    re.compile(r"^\s*/\*"),
    re.compile(r"import\s"),
    re.compile(r"from\s"),
    re.compile(r"export\s"),
    re.compile(r"console\.(log|warn|error|debug)"),
    re.compile(r"\.test\.(ts|tsx)$"),
    re.compile(r"\.stories\.(ts|tsx)$"),
    re.compile(r"__mocks__"),
    re.compile(r"spec/"),
]


def scan_unwrapped_strings(repo_dir: Path) -> list[UnwrappedString]:
    """Scan frontend source files for string literals not wrapped in t()."""
    frontend_dir = repo_dir / FRONTEND_SRC_DIR
    if not frontend_dir.exists():
        return []

    results = []

    for ext in ("*.tsx", "*.ts"):
        for filepath in frontend_dir.rglob(ext):
            rel_path = str(filepath.relative_to(repo_dir))

            if any(skip in rel_path for skip in [
                ".test.", ".spec.", ".stories.", "__mocks__", "spec/",
                "node_modules", "dist/", "lib/", "types/",
            ]):
                continue

            try:
                lines = filepath.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue

            for line_num, line in enumerate(lines, 1):
                if any(p.search(line) for p in _IGNORE_PATTERNS):
                    continue

                if _T_CALL_PATTERN.search(line) or _TN_CALL_PATTERN.search(line):
                    continue

                for pattern in _JSX_STRING_PATTERNS:
                    for match in pattern.finditer(line):
                        string_val = match.group(1)
                        if len(string_val) > 3 and not string_val.startswith("http"):
                            results.append(UnwrappedString(
                                file_path=rel_path,
                                line_number=line_num,
                                line_content=line.strip(),
                                string_value=string_val,
                            ))

    return results


def run_scan(force_fresh: bool = False) -> ScanResult:
    """Run a full i18n scan on the superset repo."""
    repo_dir = clone_repo(force_fresh=force_fresh)
    commit_sha = get_commit_sha(repo_dir)

    pot_path = repo_dir / TRANSLATIONS_DIR / "messages.pot"
    pot_total = count_pot_strings(pot_path) if pot_path.exists() else 0

    coverages = []
    translations_dir = repo_dir / TRANSLATIONS_DIR
    for locale in PRIORITY_LOCALES:
        po_path = translations_dir / locale / "LC_MESSAGES" / "messages.po"
        if po_path.exists():
            coverages.append(parse_po_file(po_path))

    unwrapped = scan_unwrapped_strings(repo_dir)

    from src.config import SUPERSET_REPO
    return ScanResult(
        locale_coverages=coverages,
        unwrapped_strings=unwrapped,
        pot_total_strings=pot_total,
        commit_sha=commit_sha,
        repo=SUPERSET_REPO,
        branch=SUPERSET_BRANCH,
    )
