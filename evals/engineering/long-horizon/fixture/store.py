import json
import pathlib


def load_state(root):
    path = pathlib.Path(root) / "installed.json"
    return json.loads(path.read_text()) if path.exists() else {"packages": {}}


def save_state(root, state):
    path = pathlib.Path(root) / "installed.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, sort_keys=True) + "\n")
