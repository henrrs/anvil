import sys


def contract():
    from contracts import Job
    assert Job("one", "mail", "value").id == "one"
    try:
        Job("", "mail", "value")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid job accepted")


def policy():
    from contracts import Job
    from types import SimpleNamespace
    from policy import ready
    ledger = SimpleNamespace(completed=set(), attempts={})
    jobs = [Job("a", "x", "1"), Job("b", "y", "2")]
    assert ready(jobs, ledger, 1) == jobs[:1] and not ledger.attempts
    ledger.completed.add("a")
    assert ready(jobs, ledger, 2) == jobs[1:]


def execution():
    from contracts import Job
    from executor import Ledger, execute
    ledger, calls = Ledger(), []
    handlers = {"x": lambda p: calls.append(("x", p)), "y": lambda p: calls.append(("y", p))}
    for job in (Job("a", "x", "1"), Job("b", "y", "2")):
        execute(job, handlers, ledger)
        execute(job, handlers, ledger)
    assert calls == [("x", "1"), ("y", "2")]
    def fail(payload):
        raise RuntimeError("failed handler")
    job = Job("c", "bad", "3", 1)
    try:
        execute(job, {"bad": fail}, ledger)
    except RuntimeError:
        pass
    assert "c" not in ledger.completed and ledger.attempts["c"] == 1
    try:
        execute(job, {"bad": fail}, ledger)
    except ValueError:
        pass
    else:
        raise AssertionError("exhausted job executed")


if __name__ == "__main__":
    {"contract": contract, "policy": policy, "execution": execution,
     "all": lambda: [case() for case in (contract, policy, execution)]}[sys.argv[1]]()
    print("PASS scheduler acceptance", sys.argv[1])
