# Superset i18n Coverage Automation

An event-driven automation that scans [anuli/superset](https://github.com/anuli/superset) for internationalization (i18n) coverage gaps and creates Devin sessions to fix them.

## What It Does

1. **Scans** the superset repo for i18n issues:
   - Parses `.po` translation files to compute per-locale coverage percentages
   - Scans frontend `.tsx`/`.ts` files for UI string literals not wrapped in `t()`
2. **Creates Devin sessions** via the API to fix the gaps found
3. **Tracks** all scan results, sessions, and PRs in a local SQLite database
4. **Reports** metrics for engineering leadership visibility

## Architecture

```
GitHub Push Event (webhook)
        |
        v
+------------------+     +------------------+     +------------------+
|   Webhook /      | --> |   i18n Scanner   | --> | Devin Session    |
|   CLI trigger    |     |   (.po coverage, |     | Orchestrator     |
|   Schedule       |     |    t() checks)   |     | (create & track) |
+------------------+     +------------------+     +------------------+
                                  |                        |
                                  v                        v
                          +------------------+     +------------------+
                          |   SQLite DB      |     |   PRs on         |
                          |   (scan_results, |     |   anuli/superset |
                          |    sessions)     |     +------------------+
                          +------------------+
                                  |
                                  v
                          +------------------+
                          |   /report        |
                          |   CLI dashboard  |
                          +------------------+
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set your Devin API token
export DEVIN_API_TOKEN="your-token-here"

# Run a scan (clones anuli/superset, analyzes i18n, prints report)
python -m src.cli scan

# Run a scan + create Devin sessions to fix gaps
python -m src.cli scan --fix

# View the observability report
python -m src.cli report

# Start the webhook server (for GitHub push events)
python -m src.cli serve --port 8000
```

## Configuration

| Environment Variable | Description | Default |
|---|---|---|
| `DEVIN_API_TOKEN` | Devin API key for session creation | Required for `--fix` |
| `SUPERSET_REPO` | GitHub repo to scan | `anuli/superset` |
| `SUPERSET_BRANCH` | Branch to scan | `master` |
| `COVERAGE_THRESHOLD` | Min translation % before flagging | `80` |
| `WEBHOOK_SECRET` | GitHub webhook secret for signature verification | Optional |
| `DB_PATH` | Path to SQLite database | `./i18n_automation.db` |

## Event Triggers

### 1. GitHub Webhook (push events)
Configure a GitHub webhook on `anuli/superset` pointing to your server:
- URL: `http://your-host:8000/webhook`
- Content type: `application/json`
- Events: `push`

### 2. Scheduled (Devin Automation)
Set up a Devin automation with a schedule trigger that invokes this tool periodically.

### 3. Manual CLI
Run `python -m src.cli scan` at any time.

## Observability

The `/report` endpoint and `cli report` command show:
- Per-locale translation coverage percentages and trends
- Number of untranslated strings per locale
- Devin sessions created, their status (running/completed/failed)
- PRs opened and their merge status
- Historical scan data for trend analysis
