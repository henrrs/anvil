import sys
import os
import tempfile
from pathlib import Path
from unittest import mock

import settings


def all_cases():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "nested" / "settings.json"
        path.parent.mkdir()
        original = b'{"custom":"preserved","revision":9}\n'
        path.write_bytes(original)
        real_replace = os.replace
        with mock.patch("settings.os.replace", side_effect=OSError("injected publish failure")):
            try:
                settings.save_settings(path, {"theme": "light"})
            except OSError:
                pass
            else:
                raise AssertionError("publication failure was swallowed")
        assert path.read_bytes() == original
        assert sorted(item.name for item in path.parent.iterdir()) == ["settings.json"]
        assert callable(real_replace)
    try:
        settings.save_settings("/tmp/ignored", [])
    except (TypeError, ValueError):
        pass
    else:
        raise AssertionError("non-mapping updates accepted")


if __name__ == "__main__":
    if sys.argv[1:] != ["all"]:
        raise SystemExit(2)
    all_cases()
