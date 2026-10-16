#!/usr/bin/env python3
"""Gracefully stop only validated OpenCode processes using Anvil's data paths."""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path

from runtime_processes import discover, read_stat


class QuiesceError(RuntimeError):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


def still_same(process: dict, binary: str) -> bool:
    pid = int(process["pid"])
    current = read_stat(pid)
    if current is None or str(current["state"]).startswith("Z"):
        return False
    if process.get("start_time") is not None and current["start_time"] != process["start_time"]:
        return False
    current_processes = discover(binary)["processes"]
    match = next((item for item in current_processes if int(item["pid"]) == pid), None)
    return bool(match and match.get("identity_verified") and match.get("start_time") == process.get("start_time"))


def send(process: dict, binary: str, sig: int) -> None:
    pid = int(process["pid"])
    pidfd = None
    if Path("/proc").is_dir() and hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
        try:
            pidfd = os.pidfd_open(pid, 0)
        except ProcessLookupError:
            return
        except OSError as exc:
            raise QuiesceError("RUNTIME_SIGNAL_FAILED", f"could not open validated OpenCode process {pid}") from exc
    try:
        if not still_same(process, binary):
            return
        if pidfd is not None:
            signal.pidfd_send_signal(pidfd, sig)
        else:
            os.kill(pid, sig)
    except ProcessLookupError:
        return
    except PermissionError as exc:
        raise QuiesceError("RUNTIME_SIGNAL_FAILED", f"could not signal validated OpenCode process {pid}") from exc
    except OSError as exc:
        raise QuiesceError("RUNTIME_SIGNAL_FAILED", f"could not signal validated OpenCode process {pid}") from exc
    finally:
        if pidfd is not None:
            os.close(pidfd)


def quiesce(binary: str, countdown: int, grace_timeout: float) -> dict:
    initial = discover(binary)
    processes = initial["processes"]
    if not processes:
        return {"stopped": 0, "forced": 0}
    if initial["uncertain"]:
        raise QuiesceError("RUNTIME_QUIESCE_FAILED", "An OpenCode process could not be scoped safely; no signal was sent")
    if initial["self_ancestor"]:
        raise QuiesceError("RUNTIME_SELF_ANCESTOR", "This upgrade is running from inside OpenCode. Run it from an external terminal; Anvil cannot safely stop its parent runtime.")

    print("OpenCode is currently running.", flush=True)
    print(f"A consistent backup requires it to be stopped.", flush=True)
    print(f"Anvil will stop {len(processes)} OpenCode process(es) in {countdown} seconds. Press Ctrl+C to cancel.", flush=True)
    try:
        for remaining in range(countdown, 0, -1):
            print(f"  Stopping in {remaining}...", flush=True)
            time.sleep(1)
    except KeyboardInterrupt as exc:
        raise QuiesceError("UPGRADE_CANCELLED", "upgrade cancelled before OpenCode was stopped") from exc

    current = discover(binary)
    if current["uncertain"]:
        raise QuiesceError("RUNTIME_QUIESCE_FAILED", "OpenCode process identity became uncertain during countdown; no signal was sent")
    if current["self_ancestor"]:
        raise QuiesceError("RUNTIME_SELF_ANCESTOR", "This upgrade is running from inside OpenCode. Run it from an external terminal; Anvil cannot safely stop its parent runtime.")
    processes = current["processes"]
    for process in processes:
        send(process, binary, signal.SIGTERM)
    print(f"Sent SIGTERM to {len(processes)} validated OpenCode process(es).", flush=True)

    deadline = time.monotonic() + max(0.0, grace_timeout)
    remaining: list[dict] = []
    while True:
        snapshot = discover(binary)
        if snapshot["uncertain"]:
            raise QuiesceError("RUNTIME_QUIESCE_FAILED", "could not verify OpenCode process identity after SIGTERM")
        remaining = snapshot["processes"]
        if not remaining or time.monotonic() >= deadline:
            break
        time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    forced = 0
    if remaining:
        print(f"{len(remaining)} OpenCode process(es) did not exit; using SIGKILL as a fallback.", flush=True)
        for process in remaining:
            send(process, binary, signal.SIGKILL)
            forced += 1

    verify_deadline = time.monotonic() + 2
    while True:
        snapshot = discover(binary)
        if snapshot["uncertain"]:
            raise QuiesceError("RUNTIME_QUIESCE_FAILED", "could not verify OpenCode shutdown")
        if not snapshot["processes"]:
            break
        if time.monotonic() >= verify_deadline:
            pids = ", ".join(str(item["pid"]) for item in snapshot["processes"])
            raise QuiesceError("RUNTIME_QUIESCE_FAILED", f"OpenCode processes remain after shutdown attempt: {pids}")
        time.sleep(0.05)
    print("OpenCode is stopped; Anvil will create the verified backup next.", flush=True)
    return {"stopped": len(processes), "forced": forced}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--countdown", type=int, default=5)
    parser.add_argument("--grace-timeout", type=float, default=10)
    args = parser.parse_args()
    try:
        quiesce(args.binary, max(0, min(args.countdown, 30)), max(0.0, min(args.grace_timeout, 30.0)))
        return 0
    except QuiesceError as exc:
        print(f"ERROR {exc.category}: {exc}", file=sys.stderr)
        return 130 if exc.category == "UPGRADE_CANCELLED" else 1
    except (OSError, ValueError) as exc:
        print(f"ERROR RUNTIME_QUIESCE_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
