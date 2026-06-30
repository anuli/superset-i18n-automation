"""
Build targeted prompts for Devin sessions that fix cosmetic / UI bugs.
"""

from src.config import SUPERSET_REPO

VERIFICATION_PENDING_MARKER = (
    "\n\n---\n"
    "**Visual verification:** Pending — "
    "a follow-up Playwright verification session will attach "
    "before/after component screenshots to this PR shortly.\n"
)

VERIFICATION_ERROR_MARKER = (
    "\n\n---\n"
    "**Visual verification:** Verification failed. "
    "Please verify the fix manually.\n"
)

VERIFICATION_DONE_MARKER = (
    "\n\n---\n"
    "**Visual verification:** Before/after component screenshots attached below.\n"
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
   **Visual verification:** Pending — a follow-up Playwright verification session will attach before/after component screenshots to this PR shortly.
"""


def build_screenshot_verification_prompt(
    pr_entries: list[dict],
) -> str:
    """Return a prompt for the single Playwright screenshot-verification session.

    Uses Playwright to render the affected component in isolation and capture
    before/after screenshots — no Docker or full Superset startup required.

    Each entry in *pr_entries* must have keys:
        issue_number, title, body, pr_url, pr_number, branch
    """
    if not pr_entries:
        return ""

    pr_list = "\n".join(
        f"  - PR #{e['pr_number']} ({e['pr_url']}): "
        f"branch `{e['branch']}`, issue #{e['issue_number']} — {e['title']}"
        for e in pr_entries
    )

    pr_details = "\n\n".join(
        f"PR #{e['pr_number']} (issue #{e['issue_number']}): {e['title']}\n"
        f"Issue description: {e.get('body', '(no details)')}"
        for e in pr_entries
    )

    return f"""Verify cosmetic fixes in {SUPERSET_REPO} using Playwright component screenshots.

PRs to verify:
{pr_list}

Issue details:
{pr_details}

Instructions:
1. Clone {SUPERSET_REPO} and check out the master branch.
2. cd superset-frontend && npm install
3. Install Playwright: npx playwright install chromium

4. For EACH PR listed above:
   a. Read the PR diff to identify the exact React component that was changed.
   b. Find an existing test, story, or usage of that component to understand
      its props and imports.
   c. Write a small Playwright script (verify_<pr_number>.ts) that:
      - Imports and renders the component in a minimal HTML page using
        Playwright's page.setContent() or by serving a small test harness.
      - Uses Superset's ThemeProvider so the component renders with correct
        styles. Import the theme from @superset-ui/core or
        src/theme.ts.
      - Renders the component with realistic props that reproduce the bug
        scenario described in the issue (e.g., long text that would overflow,
        narrow container, dark mode theme, etc.).
      - Takes a screenshot and saves it as before_<pr_number>.png.
   d. Check out the PR branch, run npm install if needed.
   e. Run the same Playwright script again, saving the screenshot as
      after_<pr_number>.png.

5. For each PR, post a comment on the PR with the before/after screenshots:
   ### Visual Verification (Playwright Component Test)
   **Before (master):**
   ![before](before_<pr_number>.png)
   **After (fix applied):**
   ![after](after_<pr_number>.png)

   Include a brief note explaining what the screenshots show and how the
   fix addresses the visual defect.

6. Update each PR description: find the line that says
   "**Visual verification:** Pending" and replace it with:
   "**Visual verification:** Before/after component screenshots attached below."

7. If Playwright cannot render a particular component (missing dependencies,
   complex providers, etc.), fall back to:
   - Running the component's existing unit/snapshot tests on both branches
     and comparing the output.
   - Posting a code-review comment explaining the CSS change and why it
     fixes the visual defect.
   - Update the PR description to say:
     "**Visual verification:** Component could not be rendered in isolation.
     Code review and test comparison attached instead."

8. After processing all PRs, stop.
"""
