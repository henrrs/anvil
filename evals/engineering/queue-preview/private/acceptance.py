"""Private acceptance tests, executed by the controller outside the model sandbox."""
import copy
import pathlib
import sys


def preview():
    from contracts import Job
    from ledger import Ledger
    from service import preview_batch, deliver_batch
    jobs = [Job("done", "h", "x", 2), Job("exhausted", "h", "y", 2),
            Job("first", "h", "a", 2), Job("second", "h", "b", 2), Job("third", "h", "c", 2)]
    ledger = Ledger()
    ledger.completed.add("done")
    ledger.attempts["exhausted"] = 2
    before = copy.deepcopy((ledger.completed, ledger.attempts))
    calls = []
    result = preview_batch(jobs, ledger, 2)
    assert result == {"ready": ["first", "second"], "skipped": [
        {"id": "done", "reason": "COMPLETED"},
        {"id": "exhausted", "reason": "RETRY_BUDGET_EXHAUSTED"},
        {"id": "third", "reason": "CAPACITY"}], "capacity": 2}
    assert (ledger.completed, ledger.attempts) == before
    assert calls == []
    for invalid in (0, -1, True, 1.5, "2"):
        try:
            preview_batch(jobs, ledger, invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid capacity accepted: {invalid!r}")
    changed = pathlib.Path("service.py").read_text()
    assert "def preview_batch" in changed


def behavior_preserved():
    from contracts import Job
    from ledger import Ledger
    from service import deliver_batch
    ledger = Ledger()
    calls = []
    jobs = [Job("a", "save", "1", 2), Job("b", "save", "2", 2)]
    handlers = {"save": lambda payload: calls.append(payload)}
    deliver_batch(jobs, handlers, ledger, 1)
    deliver_batch(jobs, handlers, ledger, 2)
    assert calls == ["1", "2"]
    assert ledger.completed == {"a", "b"}


if __name__ == "__main__":
    {"all": lambda: (preview(), behavior_preserved()), "preview": preview,
     "behavior": behavior_preserved}[sys.argv[1]]()
    print("PASS queue preview acceptance")
