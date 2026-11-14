import json
import tempfile
import unittest
from pathlib import Path

from settings import DEFAULTS, load_settings, save_settings


class SettingsTests(unittest.TestCase):
    def test_missing_file_uses_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_settings(Path(tmp) / "settings.json"), DEFAULTS)

    def test_save_merges_existing_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"revision": 4, "custom": "keep"}))
            self.assertEqual(save_settings(path, {"theme": "light"}),
                             {"revision": 4, "custom": "keep", "theme": "light"})


if __name__ == "__main__":
    unittest.main()
