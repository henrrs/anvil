"""Bounded concurrent local materialization scheduling."""

from __future__ import annotations

import threading
import unittest

from scripts.analytics.scheduler import MaterializationScheduler


class MaterializationSchedulerTests(unittest.TestCase):
    def test_parallel_tables_and_fifo_queued_work(self) -> None:
        scheduler = MaterializationScheduler(2)
        release = threading.Event()
        both_started = threading.Event()
        third_started = threading.Event()
        order: list[str] = []
        lock = threading.Lock()

        def task(name: str) -> str:
            with lock:
                order.append(name)
                if len(order) == 2:
                    both_started.set()
                if name == "third":
                    third_started.set()
            if name != "third":
                self.assertTrue(release.wait(2))
            return name

        try:
            futures = [scheduler.submit(task, name) for name in ("first", "second", "third")]
            self.assertTrue(both_started.wait(2))
            self.assertEqual(scheduler.metrics(), {"workers": 2, "queued": 1, "running": 2})
            self.assertFalse(third_started.is_set())
            release.set()
            self.assertEqual([future.result(timeout=2) for future in futures],
                             ["first", "second", "third"])
            self.assertEqual(set(order[:2]), {"first", "second"})
            self.assertEqual(order[2], "third")
            self.assertEqual(scheduler.metrics(), {"workers": 2, "queued": 0, "running": 0})
        finally:
            release.set()
            scheduler.shutdown()

    def test_cancel_queued_work_releases_queue_slot(self) -> None:
        scheduler = MaterializationScheduler(1)
        release = threading.Event()
        started = threading.Event()
        try:
            first = scheduler.submit(lambda: (started.set(), release.wait(2)))
            self.assertTrue(started.wait(2))
            queued = scheduler.submit(lambda: self.fail("cancelled work ran"))
            self.assertTrue(queued.cancel())
            self.assertEqual(scheduler.metrics(), {"workers": 1, "queued": 0, "running": 1})
            release.set()
            first.result(timeout=2)
        finally:
            release.set()
            scheduler.shutdown()
