"""
Build targeted prompts for Devin sessions that fix cosmetic / UI bugs.
"""

from src.config import SUPERSET_REPO


def build_cosmetic_fix_prompt(
    issue_number: int,
    title: str,
    body: str | None,
) -> str:
    """Return a Devin session prompt for a cosmetic bug fix."""
    body_section = body or "(no additional details provided)"

    return f"""Fix cosmetic / UI bug #{issue_number} in {SUPERSET_REPO}.

Issue title: {title}

Issue description:
{body_section}

Instructions:
1. Clone {SUPERSET_REPO} and check out the master branch.
2. Read the issue carefully. Identify the affected React component(s) or
   CSS/styled-component file(s).
3. Make the minimal change needed to fix the visual defect described in the
   issue (overflow, alignment, color, dark-mode rendering, etc.).
4. Follow existing code conventions — use styled-components or Emotion where
   the surrounding code does, reuse theme tokens from
   superset-frontend/src/theme.ts when available.
5. Build the frontend (`npm run build` in superset-frontend/) to verify there
   are no compile errors.
6. Run any related unit tests (`npm test -- --watchAll=false`).
7. Create a PR targeting the master branch with the title:
   fix(ui): {title}
   Reference #{issue_number} in the PR body.
"""
