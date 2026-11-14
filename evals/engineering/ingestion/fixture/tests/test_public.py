import tempfile
import unittest
from pathlib import Path

from contracts import LoadContract
from execution import LocalSink, execute
from inputs import from_environment
from planner import choose
from progress import Progress
from sources import FakeSqlServerSource, FileSource


class IngestionPublicTests(unittest.TestCase):
    def test_intent_validation_and_environment_adapter(self):
        self.assertEqual(from_environment({"SOURCE": "files", "DATASET": "events", "KEY": "id"}).dataset, "events")
        with self.assertRaises(ValueError):
            LoadContract("", "events", "id")

    def test_plan_uses_runtime_capabilities_and_source_capacity(self):
        intent = LoadContract("mssql", "events", "id")
        source = FakeSqlServerSource([{"id": 1}])
        plan = choose(intent, source.profile(), {"name": "local", "parallelism": 4})
        self.assertEqual(plan.runtime, "local")
        self.assertEqual(plan.parallelism, 1)

    def test_sink_effect_precedes_progress_and_updates_latest_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = FileSource([{"id": 1, "value": "old"}, {"id": 1, "value": "new"}])
            plan = choose(LoadContract("files", "events", "id"), source.profile(), {"name": "local", "parallelism": 2})
            progress = Progress(Path(tmp) / "checkpoint.json")
            sink = LocalSink("id")
            execute(plan, source, sink, progress)
            self.assertEqual(len(sink.bronze), 2)
            self.assertEqual(sink.silver[1]["value"], "new")


if __name__ == "__main__":
    unittest.main()
