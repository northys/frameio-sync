import json
import tomllib
from pathlib import Path

STATE_DIR = Path.home() / "Library/Application Support/frameio-sync"
CONFIG_PATH = STATE_DIR / "config.toml"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"missing {CONFIG_PATH}, see README.md")
    with CONFIG_PATH.open("rb") as f:
        return tomllib.load(f)


def read_json(name: str, default):
    path = STATE_DIR / name
    return json.loads(path.read_text()) if path.exists() else default


def write_json(name: str, data) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_DIR / f"{name}.tmp"
    tmp.write_text(json.dumps(data))
    tmp.chmod(0o600)
    tmp.replace(STATE_DIR / name)
