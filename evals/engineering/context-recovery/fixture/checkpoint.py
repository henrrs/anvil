import json
import pathlib


class Checkpoint:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.sequence = self.load()

    def load(self):
        if not self.path.exists():
            return 0
        return json.loads(self.path.read_text()).get("sequence", 0)

    def save(self, sequence):
        self.sequence = sequence
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"sequence": sequence}) + "\n")
