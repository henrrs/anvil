import tempfile
import unittest
from pathlib import Path

from checkpoint import Checkpoint
from events import Event
from pipeline import run_sync
from sink import DurableSink
from source import Source


class RecoveryTests(unittest.TestCase):
    def test_successful_run_persists_latest_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            events = [Event(1, "a", "one"), Event(2, "b", "two")]
            checkpoint = Checkpoint(Path(directory) / "cursor.json")
            sink = DurableSink()
            result = run_sync(Source(events), sink, checkpoint, page_size=1)
            self.assertEqual(result["sequence"], 2)
            self.assertEqual(set(sink.records), {"a", "b"})

    def test_second_run_does_not_add_records(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Source([Event(1, "a", "one")])
            checkpoint = Checkpoint(Path(directory) / "cursor.json")
            sink = DurableSink()
            run_sync(source, sink, checkpoint)
            run_sync(source, sink, checkpoint)
            self.assertEqual(sink.records, {"a": "one"})

    def test_sink_failure_never_advances_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Checkpoint(Path(directory) / "cursor.json")
            class FailedSink:
                def commit(self, _event):
                    raise OSError("injected sink failure")
            with self.assertRaises(OSError):
                run_sync(Source([Event(1, "a", "one")]), FailedSink(), checkpoint)
            self.assertEqual(checkpoint.sequence, 0)

    def test_crash_after_sink_commit_replays_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Source([Event(1, "a", "one")])
            checkpoint = Checkpoint(Path(directory) / "cursor.json")
            sink = DurableSink()
            original_save = checkpoint.save
            def interrupt_once(sequence):
                checkpoint.save = original_save
                raise OSError("injected crash before cursor publication")
            checkpoint.save = interrupt_once
            with self.assertRaises(OSError):
                run_sync(source, sink, checkpoint)
            self.assertEqual(set(sink.records), {"a"})
            self.assertEqual(checkpoint.sequence, 0)
            run_sync(source, sink, checkpoint)
            self.assertEqual(sink.records, {"a": "one"})
            self.assertEqual(checkpoint.sequence, 1)

    def test_appended_events_are_picked_up_after_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Source([Event(1, "a", "one")])
            checkpoint = Checkpoint(Path(directory) / "cursor.json")
            sink = DurableSink()
            run_sync(source, sink, checkpoint)
            source.append(Event(2, "b", "two"))
            run_sync(source, sink, checkpoint)
            self.assertEqual(checkpoint.sequence, 2)
            self.assertEqual(set(sink.records), {"a", "b"})


if __name__ == "__main__":
    unittest.main()
