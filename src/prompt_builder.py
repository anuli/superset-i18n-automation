"""
Build targeted prompts for Devin sessions that fix cosmetic / UI bugs.
"""

from src.config import SUPERSET_REPO

SCREENSHOT_PENDING_MARKER = (
    "\n\n---\n"
    "**Visual verification:** Screenshots pending — "
    "a follow-up verification session will attach before/after "
    "screenshots to this PR shortly.\n"
)

SCREENSHOT_ERROR_MARKER = (
    "\n\n---\n"
    "**Visual verification:** Screenshot verification failed. "
    "Please verify the fix manually.\n"
)

SCREENSHOT_DONE_MARKER = (
    "\n\n---\n"
    "**Visual verification:** Before/after screenshots attached below.\n"
)


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
8. At the end of the PR description, add exactly this line:
   ---
   **Visual verification:** Screenshots pending — a follow-up verification session will attach before/after screenshots to this PR shortly.
"""


def build_screenshot_verification_prompt(
    pr_entries: list[dict],
) -> str:
    """Return a prompt for the single screenshot-verification session.

    Each entry in *pr_entries* must have keys:
        issue_number, title, pr_url, pr_number, branch
    """
    if not pr_entries:
        return ""

    pr_list = "\n".join(
        f"  - PR #{e['pr_number']} ({e['pr_url']}): "
        f"branch `{e['branch']}`, issue #{e['issue_number']} — {e['title']}"
        for e in pr_entries
    )

    return f"""Verify cosmetic fixes in {SUPERSET_REPO} by taking before/after screenshots.

PRs to verify:
{pr_list}

Instructions:
1. Clone {SUPERSET_REPO} and check out the master branch.
2. Start Superset locally using Docker Compose:
   docker compose up -d
   Wait until the app is accessible at http://localhost:8088.
   Log in with admin/admin.

3. For EACH PR listed above, do the following:
   a. On the master branch (before the fix), navigate to the page described in
      the issue and take a screenshot showing the bug. Save it as
      before_<pr_number>.png.
   b. Check out the PR branch, rebuild if needed, and take a screenshot of the
      same page showing the fix applied. Save it as after_<pr_number>.png.

4. For each PR, post a comment with the before/after screenshots:
   ### Visual Verification
   **Before (master):**
   ![before](before_<pr_number>.png)
   **After (fix applied):**
   ![after](after_<pr_number>.png)

5. Also update each PR description: find the line that says
   "**Visual verification:** Screenshots pending" and replace it with:
   "**Visual verification:** Before/after screenshots attached below."

6. If you cannot start Superset or navigate to the affected page for a
   particular PR, update that PR description to say:
   "**Visual verification:** Screenshot verification failed. Please verify the fix manually."
   and post a comment explaining what went wrong.

7. After processing all PRs, stop.
"""
