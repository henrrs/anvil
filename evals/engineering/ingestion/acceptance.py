"""Behavioral assertions for the representative slice, not a production ingestion engine."""
import pathlib
import sys
import tempfile


def contract():
    from contracts import LoadContract
    from inputs import from_environment
    assert from_environment({"SOURCE": "files", "DATASET": "events", "KEY": "id"}).dataset == "events"
    for values in (("", "a", "id"), ("files", "a", "id", "unknown")):
        try:
            LoadContract(*values)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid intent accepted")
    assert set(LoadContract.__dataclass_fields__) == {"source", "dataset", "key", "mode"}


def planning():
    from contracts import LoadContract
    from planner import choose
    from sources import FakeSqlServerSource, FileSource
    intent = LoadContract("mssql", "events", "id")
    source = FakeSqlServerSource([{"id": 1}])
    assert choose(intent, source.profile(), {"name": "databricks", "parallelism": 8}).parallelism == 1
    assert choose(intent, FileSource([]).profile(), {"name": "local", "parallelism": 2}).runtime == "local"
    try:
        choose(intent, source.profile(), {"name": "local", "parallelism": 0})
    except ValueError:
        pass
    else:
        raise AssertionError("invalid runtime capacity accepted")


def recovery():
    from contracts import LoadContract
    from execution import LocalSink, execute
    from planner import choose
    from progress import Progress
    from sources import FileSource
    with tempfile.TemporaryDirectory() as name:
        source = FileSource([{"id": 1, "value": "a"}, {"id": 1, "value": "b"}])
        plan = choose(LoadContract("files", "events", "id"), source.profile(), {"name": "local", "parallelism": 2})
        progress = Progress(pathlib.Path(name) / "checkpoint.json")
        sink = LocalSink("id")
        original = progress.commit
        def interrupt_after_sink(unit):
            raise RuntimeError("crash before checkpoint")
        progress.commit = interrupt_after_sink
        try:
            execute(plan, source, sink, progress)
        except RuntimeError:
            pass
        assert not progress.committed and len(sink.bronze) == 1
        progress.commit = original
        execute(plan, source, sink, progress)
        assert len(sink.bronze) == 2 and sink.silver[1]["value"] == "b"
        reads = source.reads[:]
        execute(plan, source, sink, Progress(progress.path))
        assert source.reads == reads
        class FailedSink:
            def commit(self, unit, rows):
                raise RuntimeError("failed sink")
        fresh = Progress(pathlib.Path(name) / "failed.json")
        try:
            execute(plan, source, FailedSink(), fresh)
        except RuntimeError:
            pass
        assert not fresh.committed


if __name__ == "__main__":
    cases = {"contract": contract, "planning": planning, "recovery": recovery,
             "all": lambda: [case() for case in (contract, planning, recovery)]}
    cases[sys.argv[1]]()
    print("PASS ingestion acceptance", sys.argv[1])
