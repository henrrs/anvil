"""Mechanically check declared boundaries; semantic invariants remain judgments."""

from __future__ import annotations

import ast
from pathlib import Path

from .contracts import require
from .repository import file_path, hashes


def scope(root: Path, patterns: list[str]) -> list[str]:
    paths: set[str] = set()
    for pattern in patterns:
        if not any(c in pattern for c in "*?["):
            paths.add(pattern)
            continue
        for path in root.glob(pattern):
            require(len(paths) < 500, "Invariant scope exceeds 500 files; narrow the declared boundary.")
            file_path(root, path.relative_to(root).as_posix())
            if path.is_file():
                paths.add(path.relative_to(root).as_posix())
    return sorted(paths)


def evaluate(root: Path, invariant: dict) -> dict:
    paths = scope(root, invariant["paths"])
    observations = hashes(root, paths)
    result = {"invariant_id": invariant["id"], "kind": invariant["kind"], "files": observations,
              "result": "UNKNOWN", "findings": [], "confidence": "UNKNOWN"}
    if invariant["kind"] == "semantic":
        result["findings"] = ["Explicit semantic review is required; mechanical checks cannot prove this rule."]
        return result
    findings = []
    if not paths:
        findings.append("Declared scope has no files; conformance is not established.")
    for relative, digest in observations.items():
        if digest is None:
            findings.append(f"Missing declared file: {relative}")
            continue
        path = file_path(root, relative)
        if invariant["kind"] == "required_files":
            continue
        require(path.stat().st_size <= 1024 * 1024, "Invariant input exceeds 1 MiB; narrow the scope.")
        try:
            text = path.read_text(encoding="utf-8")
            if invariant["kind"] == "forbidden_text":
                for token in invariant["forbidden"]:
                    if token in text:
                        findings.append(f"{relative}: forbidden boundary text {token!r}")
            else:
                tree = ast.parse(text, filename=relative)
                for node in ast.walk(tree):
                    modules = []
                    if isinstance(node, ast.Import):
                        modules = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        prefix = list(Path(relative).parent.parts)
                        if node.level:
                            prefix = prefix[:max(0, len(prefix) - node.level + 1)]
                            module = ".".join([*prefix, *([node.module] if node.module else [])])
                        else:
                            module = node.module or ""
                        modules = [module, *(f"{module}.{alias.name}".strip(".") for alias in node.names)]
                    if any(module == forbidden or module.startswith(forbidden + ".")
                           for module in modules for forbidden in invariant["forbidden"]):
                        findings.append(f"{relative}:{node.lineno}: forbidden import dependency")
        except (UnicodeError, SyntaxError):
            findings.append(f"{relative}: input cannot be parsed; conformance is not established")
    result.update(result="FAIL" if findings else "PASS", findings=findings[:20],
                  omitted_findings=max(0, len(findings) - 20), confidence="OBSERVED")
    return result
