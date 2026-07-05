"""Local configuration loader. Reads secrets from .env (gitignored) — never hardcode credentials here."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"'))


_load_dotenv(REPO_ROOT / ".env")

ESPN_SWID = os.environ.get("ESPN_SWID")
ESPN_S2 = os.environ.get("ESPN_S2")

# yahoo_oauth reads/rewrites this file directly (it stores refreshed tokens back to it).
YAHOO_OAUTH_PATH = REPO_ROOT / ".yahoo_oauth.json"

# Rankings-provider session cookie + source URLs. Never name the actual source
# in code/docs/commits — see CLAUDE.md's confidentiality rule.
RANKINGS_CONFIG_PATH = REPO_ROOT / ".rankings_config.json"


def get_rankings_config(path: Path = RANKINGS_CONFIG_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — see .rankings_config.example.json")
    import json

    return json.loads(path.read_text())


def get_rankings_cookie(path: Path = RANKINGS_CONFIG_PATH) -> dict:
    cookie_str = get_rankings_config(path)["cookie"]
    name, _, value = cookie_str.partition("=")
    return {name.strip(): value.strip()}


DB_PATH = REPO_ROOT / "data" / "ffassistant.db"
