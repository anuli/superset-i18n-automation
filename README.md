# Superset Cosmetic-Bug Automation

An event-driven system that automatically creates [Devin](https://devin.ai) sessions to fix cosmetic / UI bugs filed against [anuli/superset](https://github.com/anuli/superset).

## How It Works

```
GitHub Issue Event
  (opened / labeled with #bug:cosmetic)
        |
        v
+------------------+     +------------------+     +------------------+
|  Webhook Server  | --> |   Orchestrator   | --> |   Devin API      |
|  (Flask)         |     |  (dedup, prompt, |     |  (create session)|
|  POST /webhook   |     |   track)         |     +------------------+
+------------------+     +------------------+              |
                                  |                        v
                                  v                 +------------------+
                          +------------------+      |  PR on           |
                          |  SQLite DB       |      |  anuli/superset  |
                          |  (issues,        |      +------------------+
                          |   sessions,      |
                          |   events)        |
                          +------------------+
                                  |
                                  v
                          +------------------+
                          |  report-github   |
                          |  -> GitHub issue  |
                          |  comment         |
                          +------------------+
```

1. A GitHub webhook fires when an issue is **opened** or **labeled** with `#bug:cosmetic` in `anuli/superset`.
2. The webhook handler validates the event, deduplicates (one session per issue), and builds a targeted prompt describing the cosmetic fix.
3. **Phase 1 — Fix:** A Devin session is created via the [Devin API](https://docs.devin.ai/api-reference/overview). Devin clones the repo, identifies the affected component, makes the CSS/styled-component fix, and opens a PR. The PR description includes a "Verification pending" note.
4. **Phase 2 — Verify:** A single Playwright verification session renders the affected component in isolation (no Docker needed), captures before/after screenshots on master vs. the PR branch, and posts them as PR comments. Falls back to code review + test comparison if the component can't be rendered in isolation.
5. Everything is tracked in a local SQLite database with an audit log.
6. Observability endpoints (`/report`, `/report/text`) and a CLI (`report`, `sync`, `verify`) let engineering leadership monitor throughput, success rates, and PR output.

## Quick Start

```bash
pip install -r requirements.txt

# Required: Devin API token for session creation
export DEVIN_API_TOKEN="your-token"

# Optional: GitHub token for posting comments on issues
export GITHUB_TOKEN="your-github-token"

# Start the webhook server
python -m src.cli serve --port 8000

# Or process a single issue manually
python -m src.cli process-issue 42

# Backfill: create sessions for all open cosmetic issues
python -m src.cli backfill

# Sync session statuses from Devin API
python -m src.cli sync

# Create a screenshot verification session for unverified PRs
python -m src.cli verify

# View the observability report
python -m src.cli report

# Post report as a GitHub issue comment
python -m src.cli report-github
```

## Configuration

| Environment Variable | Description | Default |
|---|---|---|
| `DEVIN_API_TOKEN` | Devin API key for session creation | Required |
| `GITHUB_TOKEN` | GitHub token (for posting issue comments) | Optional |
| `SUPERSET_REPO` | Target GitHub repo | `anuli/superset` |
| `SUPERSET_BRANCH` | Target branch for PRs | `master` |
| `COSMETIC_LABEL` | Label that triggers automation | `#bug:cosmetic` |
| `WEBHOOK_SECRET` | GitHub webhook HMAC secret | Optional |
| `DB_PATH` | Path to SQLite database | `./cosmetic_automation.db` |

## Event Triggers

### GitHub Webhook (recommended)
Configure a GitHub webhook on `anuli/superset`:
- **URL:** `https://your-host/webhook`
- **Content type:** `application/json`
- **Events:** Issues
- **Secret:** (optional, set `WEBHOOK_SECRET` to match)

The automation fires on:
- `issues.opened` — if the issue already has the `#bug:cosmetic` label
- `issues.labeled` — when the `#bug:cosmetic` label is added to an existing issue

### Devin Automation (built-in)
A Devin automation can be configured to trigger on GitHub issue events directly, without running a separate webhook server. See the Devin automation section below.

### Manual / Backfill
- `python -m src.cli process-issue <NUMBER>` — process a single issue
- `python -m src.cli backfill` — fetch all open `#bug:cosmetic` issues and create sessions for any without one

## Observability

The system answers: *"If I were an engineering leader, how would I know this is working?"*

After each automation run, a **markdown summary** is posted as a comment on a pinned GitHub issue (`automation-status` label) in `anuli/superset`. No server or dashboard needed — just check the issue thread.

### Report contents

| Metric | Description |
|--------|-------------|
| Issues tracked | Total cosmetic issues processed |
| Sessions created | Devin sessions launched |
| PRs produced | Sessions that resulted in a PR |
| Success rate | % of sessions → PR |
| Avg time to PR | Mean session duration for finished PRs |
| Verification status | Verified / pending / errors |
| Throughput | PRs in last 24h and 7d |
| Session table | Per-issue status, PR link, verification status |
| Event log | Recent audit events (collapsible) |

### How to use

```bash
# Print the markdown report to stdout
python -m src.cli report

# Post the report as a GitHub issue comment (requires GITHUB_TOKEN)
python -m src.cli report-github
```

The scheduled automation runs `report-github` after each batch, so reports accumulate automatically on the status issue.

### Other endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /report` | JSON report with all metrics |
| `GET /report/text` | Markdown report as plain text |
| `POST /sessions/sync` | Poll Devin API to update session statuses |
| `POST /sessions/verify` | Create Playwright verification session |

### Playwright verification
`python -m src.cli verify` creates a single Devin session that uses Playwright to render affected components in isolation and capture before/after screenshots — no Docker required (~2-3 min vs 20+).

## Tests

```bash
python -m pytest tests/ -v
```

## Why Devin?

Cosmetic/UI bugs are uniquely suited for Devin automation because:
1. **Visual verification** — Devin can spin up Superset, navigate to the affected page, and screenshot before/after. Pure code-editing tools can't do this.
2. **Full-stack environment** — fixing these bugs requires running a Python backend + React frontend + database. Devin's VM handles this natively.
3. **Scoped, pattern-based fixes** — each bug typically involves a single CSS/styled-component change, following repeating patterns (overflow, alignment, dark-mode tokens).
4. **Steady inflow** — the `#bug:cosmetic` label in apache/superset averages 3+ new issues per month.
