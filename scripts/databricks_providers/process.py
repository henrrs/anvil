"""Bounded subprocess runner for Databricks provider adapters."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import Mapping, Sequence

from . import timeouts


MAX_CAPTURE_BYTES = 4_000_000


@dataclass(frozen=True)
class ProcessResult:
    stdout: str
    stderr: str
    returncode: int
    elapsed_ms: int


class ProcessFailure(RuntimeError):
    def __init__(self, category: str, message: str, *, elapsed_ms: int,
                 timeout_seconds: float | None = None):
        super().__init__(message)
        self.category = category
        self.elapsed_ms = elapsed_ms
        self.timeout_seconds = timeout_seconds


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None and os.name != "posix":
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        pass
    try:
        process.communicate(timeout=timeouts.seconds_for("process_terminate_grace"))
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    process.communicate()


def run(command: Sequence[str], *, env: Mapping[str, str], timeout: float,
        input_text: str | None = None, cwd: str | None = None) -> ProcessResult:
    if not command or timeout <= 0:
        raise ValueError("a command and positive timeout are required")
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=dict(env),
            start_new_session=(os.name == "posix"),
            close_fds=True,
        )
    except OSError as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        raise ProcessFailure("PROVIDER_NOT_INSTALLED", "provider executable could not be started",
                             elapsed_ms=elapsed) from exc
    selector = selectors.DefaultSelector()
    stdout = bytearray()
    stderr = bytearray()
    buffers = {"stdout": stdout, "stderr": stderr}
    assert process.stdout is not None and process.stderr is not None
    for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, name)
    input_data = memoryview(input_text.encode("utf-8")) if input_text is not None else memoryview(b"")
    input_offset = 0
    if process.stdin is not None:
        os.set_blocking(process.stdin.fileno(), False)
        if input_data:
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
        else:
            process.stdin.close()
    deadline = started + timeout
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate(process)
                elapsed = int((time.monotonic() - started) * 1000)
                raise ProcessFailure("CLI_PROCESS_TIMEOUT", "provider process exceeded its operation timeout",
                                     elapsed_ms=elapsed, timeout_seconds=timeout)
            events = selector.select(min(remaining, 0.2))
            for key, mask in events:
                stream = key.fileobj
                if key.data == "stdin":
                    try:
                        written = os.write(stream.fileno(), input_data[input_offset:input_offset + 65536])
                    except (BrokenPipeError, OSError):
                        written = len(input_data) - input_offset
                    input_offset += written
                    if input_offset >= len(input_data):
                        selector.unregister(stream)
                        stream.close()
                    continue
                try:
                    chunk = os.read(stream.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(stream)
                    stream.close()
                    continue
                target = buffers[key.data]
                if len(stdout) + len(stderr) + len(chunk) > MAX_CAPTURE_BYTES:
                    _terminate(process)
                    elapsed = int((time.monotonic() - started) * 1000)
                    raise ProcessFailure("CLI_OUTPUT_INVALID",
                                         "provider output exceeded Anvil's bounded capture limit",
                                         elapsed_ms=elapsed)
                target.extend(chunk)
        returncode = process.wait()
    except ProcessFailure:
        raise
    except BaseException:
        _terminate(process)
        raise
    finally:
        selector.close()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
    elapsed = int((time.monotonic() - started) * 1000)
    return ProcessResult(stdout.decode("utf-8", errors="replace"),
                         stderr.decode("utf-8", errors="replace"),
                         int(returncode), elapsed)
