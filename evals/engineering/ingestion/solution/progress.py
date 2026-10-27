import json
import os
import tempfile
from pathlib import Path


class Progress:
    def __init__(self, path):
        self.path = Path(path)
        self.committed = set(json.loads(self.path.read_text()) if self.path.exists() else [])

    def commit(self, unit):
        updated = self.committed | {unit}
        descriptor, name = tempfile.mkstemp(dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w") as stream:
                json.dump(sorted(updated), stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        self.committed = updated
