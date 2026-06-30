import os
from pathlib import Path


SUPERSET_REPO = os.environ.get("SUPERSET_REPO", "anuli/superset")
SUPERSET_BRANCH = os.environ.get("SUPERSET_BRANCH", "master")

DEVIN_API_TOKEN = os.environ.get("DEVIN_API_TOKEN", "")
DEVIN_API_BASE = os.environ.get("DEVIN_API_BASE", "https://api.devin.ai/v1")

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

COSMETIC_LABEL = os.environ.get("COSMETIC_LABEL", "#bug:cosmetic")

DB_PATH = os.environ.get("DB_PATH", str(Path(__file__).parent.parent / "cosmetic_automation.db"))
