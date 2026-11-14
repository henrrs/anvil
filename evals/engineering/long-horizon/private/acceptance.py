"""Private multi-milestone acceptance checks; never mounted into the model sandbox."""
import json
import pathlib
import subprocess
import sys
import tempfile


def resolution():
    from resolver import resolve
    manifest = {"packages": [{"name": "worker", "version": "==1.0.0"}]}
    first = resolve(manifest)
    second = resolve(manifest)
    assert [item["name"] for item in first] == ["core", "store", "api", "worker"]
    assert first == second
    assert {item["name"]: item["version"] for item in first}["core"] == "1.2.0"
    for invalid in ({"packages": [{"name": "missing", "version": "==1.0.0"}]},
                    {"packages": [{"name": "worker", "version": "==9.0.0"}]},
                    {"packages": [{"name": "core", "version": "==1.0.0"}, {"name": "core", "version": "==1.2.0"}]},
                    {"packages": [{"name": "legacy-client", "version": "==1.0.0"}, {"name": "modern-client", "version": "==1.0.0"}]}):
        try:
            resolve(invalid)
        except (ValueError, KeyError):
            pass
        else:
            raise AssertionError(f"invalid dependency graph accepted: {invalid}")
    cycle = {"a": {"1.0.0": {"dependencies": {"b": ">=1.0.0"}}},
             "b": {"1.0.0": {"dependencies": {"a": ">=1.0.0"}}}}
    try:
        resolve({"packages": [{"name": "a", "version": "==1.0.0"}]}, cycle)
    except (ValueError, KeyError):
        pass
    else:
        raise AssertionError("dependency cycle was not rejected")


def installation_rollback():
    from installer import install
    from store import load_state
    manifest = {"packages": [{"name": "worker", "version": "==1.0.0"}]}
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        (root / "keep.txt").write_text("user data")
        install({"packages": [{"name": "core", "version": "==1.0.0"}]}, root)
        old_state = load_state(root)
        old_core = (root / "packages/core/package.json").read_bytes()
        try:
            install(manifest, root, fail_after=1)
        except RuntimeError:
            pass
        else:
            raise AssertionError("injected activation failure did not occur")
        assert load_state(root) == old_state
        assert (root / "packages/core/package.json").read_bytes() == old_core
        assert not (root / "packages/worker").exists()
        assert (root / "keep.txt").read_text() == "user data"
        assert not list(root.glob(".anvil-stage-*"))


def cli_flow():
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({"packages": [{"name": "worker", "version": "==1.0.0"}]}))
        plan = subprocess.run([sys.executable, "cli.py", "plan", "--manifest", str(manifest)],
                              capture_output=True, text=True, timeout=10)
        assert plan.returncode == 0, plan.stderr
        assert [item["name"] for item in json.loads(plan.stdout)] == ["core", "store", "api", "worker"]
        install = subprocess.run([sys.executable, "cli.py", "install", "--manifest", str(manifest), "--root", str(root / "target")],
                                 capture_output=True, text=True, timeout=10)
        assert install.returncode == 0, install.stderr
        assert (root / "target/installed.json").is_file()
        invalid = subprocess.run([sys.executable, "cli.py", "plan", "--manifest", str(root / "absent.json")],
                                 capture_output=True, text=True, timeout=10)
        assert invalid.returncode != 0


if __name__ == "__main__":
    {"all": lambda: (resolution(), installation_rollback(), cli_flow()),
     "resolution": resolution, "rollback": installation_rollback, "cli": cli_flow}[sys.argv[1]]()
    print("PASS long-horizon acceptance")
