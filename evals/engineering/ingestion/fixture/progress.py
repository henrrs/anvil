import json
from pathlib import Path


class Progress:
    def __init__(self, path):
        self.path = Path(path)
        self.committed = set(json.loads(self.path.read_text()) if self.path.exists() else [])

    def commit(self, unit):
        self.committed.add(unit)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(sorted(self.committed)), encoding="utf-8")
