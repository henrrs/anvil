import json
import pathlib
import re

NAME = re.compile(r"^[a-z][a-z0-9-]{0,62}$")


def load_manifest(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
