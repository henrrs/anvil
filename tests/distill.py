#!/usr/bin/env python3
"""Deterministic checks for distillation evidence handling and source idempotence."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "distill"


def call(args: list[str], env: dict[str, str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, env=env, input=input_text, text=True, capture_output=True, check=True, timeout=30)


def fixtures() -> None:
    expected = json.loads((FIXTURES / "expectations.json").read_text(encoding="utf-8"))
    a = FIXTURES / "case-a"
    b = FIXTURES / "case-b"
    c = FIXTURES / "case-c"
    d = FIXTURES / "case-d"
    e = FIXTURES / "case-e"
    f = FIXTURES / "case-f"
    g = FIXTURES / "case-g"
    assert expected["case-a"]["status"] == "corroborated"
    assert "bounded attempt count" in (a / "current.md").read_text(encoding="utf-8")
    assert "bounded exponential backoff" in (a / "src/ingestion.py").read_text(encoding="utf-8")
    assert "retry_delay" in (a / "tests/test_ingestion.py").read_text(encoding="utf-8")

    assert expected["case-b"]["status"] == "conflicted"
    assert "append-only" in (b / "stale.md").read_text(encoding="utf-8")
    assert "UPDATE" in (b / "src/history_store.py").read_text(encoding="utf-8")
    assert "INSERT" in (b / "src/history_store.py").read_text(encoding="utf-8")
    assert "len(repository.history" in (b / "tests/test_history_store.py").read_text(encoding="utf-8")

    assert expected["case-c"]["status"] == "corroborated"
    assert (c / "old/scd2_legacy.py").is_file()
    active = "\n".join(p.read_text(encoding="utf-8") for folder in (c / "src", c / "tests") for p in folder.rglob("*.py"))
    assert "append_event" in active and "scd2_legacy" not in active

    assert expected["case-d"]["status"] == "conflicted"
    assert "must never store raw" in (d / "security-policy.md").read_text(encoding="utf-8")
    assert "cache[provider] = raw_token" in (d / "src/token_cache.py").read_text(encoding="utf-8")
    assert "persists_raw_value" in (d / "tests/test_token_cache.py").read_text(encoding="utf-8")

    assert expected["case-e"]["status"] == "historical"
    assert "2023" in (e / "architecture-2023.md").read_text(encoding="utf-8")
    assert expected["case-f"]["status"] == "conflicted"
    assert "numPartitions = 8" in (f / "platform.md").read_text(encoding="utf-8")
    assert '"numPartitions": 16' in (f / "config/job.json").read_text(encoding="utf-8")
    assert "JOB_CONFIG[\"numPartitions\"]" in (f / "src/pipeline.py").read_text(encoding="utf-8")
    assert "== 16" in (f / "tests/test_pipeline.py").read_text(encoding="utf-8")
    assert expected["case-g"]["status"] == "image-not-inspected"
    image_fixture = g / expected["case-g"]["path"]
    assert not image_fixture.exists()
    assert "![Pipeline topology](images/pipeline-topology.png)" in (g / "unavailable-diagram.md").read_text(encoding="utf-8")
    command = (ROOT / "config/commands/distill.md").read_text(encoding="utf-8").lower()
    for phrase in ("source_registry.py plan", "active code path", "normative truth", "implementation truth", "historical", "image", "unchanged"):
        assert phrase in command, f"/distill prompt does not preserve required evidence rule: {phrase}"
    print("PASS /distill fixtures cover corroboration, stale docs, inactive code, policy conflict, historical evidence, drift and unavailable images")


def source_idempotency() -> None:
    with tempfile.TemporaryDirectory(prefix="anvil-distill-idempotency-", dir="/tmp") as directory:
        root = pathlib.Path(directory)
        home, data = root / "home", root / "data"
        home.mkdir()
        env = {**os.environ, "HOME": str(home), "XDG_DATA_HOME": str(data)}
        source = root / "platform.md"
        source.write_text("## Retry policy\n\nUse bounded retries with jitter for remote ingestion.\n", encoding="utf-8")
        registry = ROOT / "scripts/source_registry.py"
        memory = ROOT / "scripts/memory.py"
        inspected = call([sys.executable, str(registry), "inspect", str(source)], env)
        first = json.loads(inspected.stdout)
        assert first["registry_status"] == "new"
        source_metadata: dict[str, str] = {
            "type": "document", "path": first["path"], "sha256": first["sha256"],
            "section": "Retry policy", "line_start": "1", "line_end": "3",
        }
        raw = {
            "id": "retry-policy-fixture", "type": "lesson", "scope": "project:fixture",
            "tags": ["retry", "ingestion"], "aliases": ["retentativas", "backoff"],
            "source": source_metadata, "confidence": "confirmed", "status": "corroborated",
            "evidence": ["platform.md:1-3"],
            "body": "Use bounded exponential retries with jitter when remote ingestion fails.",
        }
        written = call([sys.executable, str(memory), "write-json"], env, input_text=json.dumps(raw))
        assert "Wrote " in written.stdout
        first["memory_ids"] = [raw["id"]]
        call([sys.executable, str(registry), "record"], env, input_text=json.dumps(first))
        registry_path = data / "anvil" / "sources" / f"{first['source_id']}.json"
        memory_path = next((data / "anvil/memory").rglob("retry-policy-fixture.md"))
        metadata_before = registry_path.read_bytes()
        memory_before = memory_path.read_bytes()
        status = json.loads(call([sys.executable, str(registry), "inspect", str(source)], env).stdout)
        assert status["registry_status"] == "unchanged"
        plan = json.loads(call([sys.executable, str(registry), "plan"], env, input_text=json.dumps([status])).stdout)
        assert plan == {"action": "skip", "created": 0, "updated": 0, "duplicate_memories": 0}
        assert registry_path.read_bytes() == metadata_before and memory_path.read_bytes() == memory_before

        # Force the documented no-rg fallback and verify a Portuguese alias plus English query.
        search_env = {**env, "PATH": "/nonexistent"}
        result = call([sys.executable, str(memory), "search", "retentativas", "backoff"], search_env)
        assert "retry-policy-fixture" in result.stdout
        entry = memory_path.read_text(encoding="utf-8")
        assert "sha256:" in entry and "section:" in entry and "line_start:" in entry
        assert "aliases:" in entry and "status: 'corroborated'" in entry

        source.write_text(source.read_text(encoding="utf-8") + "\nChanged wording.\n", encoding="utf-8")
        changed = json.loads(call([sys.executable, str(registry), "inspect", str(source)], env).stdout)
        assert changed["registry_status"] == "changed"
        changed_plan = json.loads(call([sys.executable, str(registry), "plan"], env, input_text=json.dumps([changed])).stdout)
        assert changed_plan["action"] == "distill"
        print("PASS source registry provenance, hash drift detection, multilingual alias search, and unchanged-source idempotence")


def main() -> int:
    fixtures()
    source_idempotency()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, subprocess.CalledProcessError, OSError, ValueError) as exc:
        print(f"FAIL distillation checks: {exc}", file=sys.stderr)
        raise SystemExit(1)
