"""Private recovery and regression grader; runs only in the controller process."""
import pathlib
import tempfile
import sys


def recovery():
    from checkpoint import Checkpoint
    from events import Event
    from pipeline import run_sync
    from sink import DurableSink
    from source import Source

    with tempfile.TemporaryDirectory() as directory:
        cursor = pathlib.Path(directory) / "cursor.json"
        source = Source([Event(1, "a", "one"), Event(2, "b", "two"), Event(3, "c", "three")])
        sink = DurableSink()
        checkpoint = Checkpoint(cursor)

        class FailBeforeCommit(DurableSink):
            def commit(self, event):
                raise RuntimeError("injected pre-commit failure")

        failed = Checkpoint(pathlib.Path(directory) / "failed.json")
        try:
            run_sync(source, FailBeforeCommit(), failed, page_size=1)
        except RuntimeError:
            pass
        else:
            raise AssertionError("pre-commit failure was not surfaced")
        assert failed.sequence == 0

        class CommitThenInterrupt(DurableSink):
            def __init__(self):
                super().__init__()
                self.once = True

            def commit(self, event):
                result = super().commit(event)
                if self.once:
                    self.once = False
                    raise RuntimeError("injected crash after durable sink commit")
                return result

        interrupted_sink = CommitThenInterrupt()
        try:
            run_sync(source, interrupted_sink, checkpoint, page_size=1)
        except RuntimeError:
            pass
        else:
            raise AssertionError("post-commit interruption was not surfaced")
        assert checkpoint.sequence == 0 and set(interrupted_sink.records) == {"a"}
        resumed = run_sync(source, interrupted_sink, checkpoint, page_size=1)
        assert resumed["sequence"] == 3
        assert interrupted_sink.records == {"a": "one", "b": "two", "c": "three"}
        assert checkpoint.sequence == 3

        source.append(Event(4, "d", "four"))
        again = run_sync(source, interrupted_sink, checkpoint, page_size=2)
        assert again["sequence"] == 4 and interrupted_sink.records["d"] == "four"
        assert len(interrupted_sink.records) == 4


def atomic_checkpoint():
    from checkpoint import Checkpoint
    with tempfile.TemporaryDirectory() as directory:
        target = pathlib.Path(directory) / "state/cursor.json"
        checkpoint = Checkpoint(target)
        checkpoint.save(7)
        assert Checkpoint(target).sequence == 7
        assert not list(target.parent.glob("*.tmp"))


if __name__ == "__main__":
    {"all": lambda: (recovery(), atomic_checkpoint()), "recovery": recovery,
     "atomic": atomic_checkpoint}[sys.argv[1]]()
    print("PASS context-recovery acceptance")
