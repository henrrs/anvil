import unittest
from unittest import mock

from contracts import Job
from ledger import Ledger
from policy import select_ready
from service import deliver_batch, preview_batch


class DispatcherTests(unittest.TestCase):
    def test_selection_is_stable_and_bounded(self):
        jobs = [Job("a", "save", "1"), Job("b", "save", "2")]
        self.assertEqual([job.id for job in select_ready(jobs, Ledger(), 1)], ["a"])

    def test_delivery_acknowledges_only_success(self):
        ledger = Ledger()
        jobs = [Job("ok", "save", "1"), Job("bad", "fail", "2", 1)]
        result = deliver_batch(jobs, {"save": lambda _value: None, "fail": lambda _value: (_ for _ in ()).throw(RuntimeError())}, ledger, 2)
        self.assertEqual([row[1] for row in result], ["COMPLETED", "FAILED"])
        self.assertEqual(ledger.completed, {"ok"})
        self.assertEqual(ledger.attempts, {"bad": 1})

    def test_preview_is_ordered_capacity_limited_and_side_effect_free(self):
        ledger = Ledger()
        ledger.acknowledge("done")
        ledger.attempts["exhausted"] = 1
        jobs = [Job("done", "save", "x"), Job("exhausted", "save", "x", 1),
                Job("first", "save", "x"), Job("second", "save", "x")]
        before = (set(ledger.completed), dict(ledger.attempts))
        with mock.patch("service.execute_one", side_effect=AssertionError("preview executed a job")):
            preview = preview_batch(jobs, ledger, 1)
        self.assertEqual(preview["ready"], ["first"])
        self.assertEqual([row["id"] for row in preview["skipped"]], ["done", "exhausted", "second"])
        self.assertEqual((ledger.completed, ledger.attempts), before)


if __name__ == "__main__":
    unittest.main()
