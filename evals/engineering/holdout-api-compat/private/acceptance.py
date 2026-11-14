import json
import sys
from status import render_status


def all_cases():
    detail = {"jobs": 2}
    assert render_status("worker", "ready", detail) == "worker: ready jobs=2"
    assert detail == {"jobs": 2}
    encoded = render_status("worker", "ready", detail, as_json=True)
    assert json.loads(encoded) == {"name": "worker", "state": "ready", "details": detail}
    assert encoded == json.dumps({"name": "worker", "state": "ready", "details": detail}, sort_keys=True, separators=(",", ":"))
    try:
        render_status("worker", "unknown")
    except ValueError:
        pass
    else:
        raise AssertionError("unsupported state accepted")


if __name__ == "__main__":
    if sys.argv[1:] != ["all"]:
        raise SystemExit(2)
    all_cases()
