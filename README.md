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
                          |  /report         |
                          |  /report/text    |
                          |  CLI dashboard   |
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

### Metrics available via `/report` (JSON) and `/report/text` (plain text):
- **Issues tracked** — total cosmetic issues processed
- **Sessions created** — total Devin sessions launched
- **Sessions with PRs** — how many sessions produced a pull request
- **PR success rate** — percentage of sessions that resulted in a PR
- **Session status breakdown** — created / running / finished / error
- **Recent events** — audit log of issue receipts, session creations, status changes

### Session sync
`POST /sessions/sync` or `python -m src.cli sync` polls the Devin API to update session statuses and detect newly created PRs.

### Playwright verification
`POST /sessions/verify` or `python -m src.cli verify` creates a single Devin session that uses Playwright to render affected components in isolation and capture before/after screenshots — no Docker or full Superset startup required (~2-3 min vs 20+). Falls back to code review + test comparison if a component can't be rendered standalone. PR descriptions are updated from "Pending" to "Screenshots attached" (or a fallback note).

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
