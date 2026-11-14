import json
import pathlib
import tempfile
import unittest
from pathlib import Path

from manifest import load_manifest
from resolver import resolve
from installer import install


class PackageFlowTests(unittest.TestCase):
    def test_transitive_dependencies_are_dependencies_first(self):
        plan = resolve({"packages": [{"name": "worker", "version": "==1.0.0"}]})
        self.assertEqual([item["name"] for item in plan], ["core", "store", "api", "worker"])

    def test_install_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = {"packages": [{"name": "worker", "version": "==1.0.0"}]}
            first = install(manifest, directory)
            second = install(manifest, directory)
            self.assertTrue(first["installed"])
            self.assertEqual(second["changed"], [])

    def test_manifest_is_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "manifest.json"
            path.write_text(json.dumps({"packages": []}))
            self.assertEqual(load_manifest(path), {"packages": []})

    def test_unknown_package_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve({"packages": [{"name": "missing", "version": "==1.0.0"}]})

    def test_dependency_cycles_are_rejected(self):
        catalog = {
            "alpha": {"1.0.0": {"dependencies": {"beta": "==1.0.0"}}},
            "beta": {"1.0.0": {"dependencies": {"alpha": "==1.0.0"}}},
        }
        with self.assertRaises(ValueError):
            resolve({"packages": [{"name": "alpha", "version": "==1.0.0"}]}, catalog=catalog)

    def test_failed_activation_restores_state_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unrelated = root / "notes.txt"
            unrelated.write_text("keep")
            prior_state = {"packages": {"old": "1.0.0"}}
            (root / "installed.json").write_text(json.dumps(prior_state))
            with self.assertRaises(Exception):
                install({"packages": [{"name": "worker", "version": "==1.0.0"}]}, root, fail_after=1)
            self.assertEqual(json.loads((root / "installed.json").read_text()), prior_state)
            self.assertEqual(unrelated.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
