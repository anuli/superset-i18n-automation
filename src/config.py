import os
from pathlib import Path


SUPERSET_REPO = os.environ.get("SUPERSET_REPO", "anuli/superset")
SUPERSET_BRANCH = os.environ.get("SUPERSET_BRANCH", "master")
SUPERSET_CLONE_URL = f"https://github.com/{SUPERSET_REPO}.git"

DEVIN_API_TOKEN = os.environ.get("DEVIN_API_TOKEN", "")
DEVIN_API_BASE = "https://api.devin.ai/v1"

COVERAGE_THRESHOLD = int(os.environ.get("COVERAGE_THRESHOLD", "80"))

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

DB_PATH = os.environ.get("DB_PATH", str(Path(__file__).parent.parent / "i18n_automation.db"))

WORK_DIR = Path(os.environ.get("WORK_DIR", "/tmp/superset-i18n-workdir"))

TRANSLATIONS_DIR = "superset/translations"
FRONTEND_SRC_DIR = "superset-frontend/src"

PRIORITY_LOCALES = ["de", "es", "fr", "ja", "ko", "pt_BR", "ru", "zh", "zh_TW"]
