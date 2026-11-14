import json
from pathlib import Path

DEFAULTS = {"revision": 1, "theme": "dark"}


def load_settings(path):
    target = Path(path)
    return json.loads(target.read_text(encoding="utf-8")) if target.exists() else dict(DEFAULTS)


def save_settings(path, updates):
    target = Path(path)
    current = load_settings(target)
    current.update(updates)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(current) + "\n", encoding="utf-8")
    return current
