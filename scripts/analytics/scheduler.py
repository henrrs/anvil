"""FIFO, bounded materialization execution isolated from catalog and chat work."""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable


class MaterializationScheduler:
    def __init__(self, workers: int = 2) -> None:
        if type(workers) is not int or not 1 <= workers <= 8:
            raise ValueError("Materialization workers must be between 1 and 8")
        self.workers = workers
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="anvil-materialization")
        self._guard = threading.Lock()
        self._pending = 0
        self._running = 0

    def submit(self, fn: Callable[..., Any], *args: Any) -> Future[Any]:
        with self._guard:
            self._pending += 1

        def work() -> Any:
            with self._guard:
                self._pending -= 1
                self._running += 1
            try:
                return fn(*args)
            finally:
                with self._guard:
                    self._running -= 1

        try:
            future = self._pool.submit(work)
        except RuntimeError:
            with self._guard:
                self._pending -= 1
            raise

        def cancelled(done: Future[Any]) -> None:
            if done.cancelled():
                with self._guard:
                    self._pending -= 1

        future.add_done_callback(cancelled)
        return future

    def metrics(self) -> dict[str, int]:
        with self._guard:
            return {"workers": self.workers, "queued": self._pending, "running": self._running}

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=False)
