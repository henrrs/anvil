#!/usr/bin/env python3
"""Explicit-only file memory for Anvil. Standard library only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


MEMORY_TYPES = {"fact", "decision", "lesson", "project"}
CONFIDENCE = {"confirmed", "high", "medium", "low", "unverified"}
SOURCE_TYPES = {"user-explicit", "repository", "code", "document", "url", "commit", "test", "other"}
SOURCE_FIELDS = {
    "type", "path", "url", "commit", "note", "section", "sha256", "repository",
    "line_start", "line_end", "imported",
}
STATUSES = {"sourced", "corroborated", "conflicted", "historical", "uncertain"}


def memory_root() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "anvil" / "memory"


def data_root() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "anvil"


def slug(value: str, *, max_length: int = 64) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    result = result[:max_length].strip("-")
    if not result or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", result):
        raise ValueError("id/project slug must contain letters or numbers")
    return result


def quote_yaml(value: str) -> str:
    return "'" + value.replace("'", "''").replace("\r", "") + "'"


def parse_entry(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return None
    try:
        end = lines.index("---", 1)
    except ValueError:
        return None
    meta: dict[str, Any] = {"tags": [], "aliases": [], "evidence": [], "source": {}}
    section = ""
    for line in lines[1:end]:
        if line.startswith("  ") and section == "source":
            match = re.fullmatch(r"  ([a-z_]+):\s*'(.*)'", line)
            if match:
                meta["source"][match.group(1)] = match.group(2).replace("''", "'")
            continue
        if line.startswith("  - ") and section in {"tags", "aliases", "evidence"}:
            meta[section].append(line[4:].strip().strip("'").replace("''", "'"))
            continue
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        section = key
        raw = raw.strip()
        if key in ("id", "type", "scope", "confidence", "status", "created", "updated"):
            meta[key] = raw[1:-1].replace("''", "'") if len(raw) >= 2 and raw[0] == raw[-1] == "'" else raw
    meta["body"] = "\n".join(lines[end + 1 :]).strip()
    meta["path"] = str(path)
    return meta


def entries(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    result = []
    for path in root.rglob("*.md"):
        if path.is_file() and not path.is_symlink():
            item = parse_entry(path)
            if item is not None:
                result.append(item)
    return result


def valid_entry(path: Path) -> bool:
    item = parse_entry(path)
    if not item:
        return False
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", str(item.get("id", ""))):
        return False
    if item.get("type") not in MEMORY_TYPES:
        return False
    if not re.fullmatch(r"(?:company|project(?::[A-Za-z0-9_. -]+)?)", str(item.get("scope", ""))):
        return False
    if not isinstance(item.get("tags"), list) or not isinstance(item.get("aliases"), list) or not isinstance(item.get("evidence"), list):
        return False
    source = item.get("source")
    if not isinstance(source, dict) or source.get("type") not in SOURCE_TYPES:
        return False
    if item.get("confidence") not in CONFIDENCE or not item.get("body", "").strip():
        return False
    status = item.get("status")
    return status is None or status in STATUSES


def audit(root: Path | None = None) -> dict[str, int]:
    location = root or memory_root()
    files = [path for path in location.rglob("*.md") if path.is_file() and not path.is_symlink()] if location.is_dir() else []
    valid = sum(valid_entry(path) for path in files)
    return {"valid": valid, "invalid": len(files) - valid, "files": len(files)}


def candidate_files(root: Path, terms: list[str]) -> set[Path] | None:
    if not terms or not root.is_dir():
        return set()
    if not shutil_which("rg"):
        return None
    found: set[Path] = set()
    for term in terms:
        proc = subprocess.run(
            ["rg", "-l", "-i", "-F", "--hidden", "--glob", "*.md", "--", term, str(root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        if proc.returncode in (0, 1):
            found.update(Path(line) for line in proc.stdout.splitlines() if line)
    return found


def shutil_which(name: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def scored_matches(root: Path, query: str) -> list[tuple[int, dict[str, Any]]]:
    def normalize(value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", value.casefold())
        return "".join(char for char in decomposed if not unicodedata.combining(char))

    terms = list(dict.fromkeys(re.findall(r"(?u)[^\W_][\w-]{1,}", normalize(query))))
    candidate_paths = candidate_files(root, terms)
    corpus = entries(root) if candidate_paths is None else [
        item for path in candidate_paths if (item := parse_entry(path)) is not None
    ]
    matches: list[tuple[int, dict[str, Any]]] = []
    for item in corpus:
        searchable = normalize(" ".join(
            [Path(item["path"]).stem, item.get("id", ""), item.get("type", ""), item.get("scope", ""),
             " ".join(item.get("tags", [])), " ".join(item.get("aliases", [])), item.get("body", "")]
        ))
        score = sum(1 for term in terms if term in searchable)
        if score:
            matches.append((score, item))
    matches.sort(key=lambda row: (-row[0], row[1].get("id", "")))
    return matches


def stale_memory_ids() -> set[str]:
    stale: set[str] = set()
    registry = data_root() / "sources"
    if not registry.is_dir():
        return stale
    for manifest_path in registry.glob("*.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict) or not isinstance(manifest.get("memory_ids"), list):
                continue
            source_path = manifest.get("absolute_path")
            if not isinstance(source_path, str) or not source_path:
                continue
            path = Path(source_path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() and not path.is_symlink() else None
            if digest != manifest.get("sha256"):
                stale.update(item for item in manifest["memory_ids"] if isinstance(item, str))
        except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
            continue
    return stale


def show_matches(matches: list[tuple[int, dict[str, Any]]], limit: int, stale_ids: set[str] | None = None) -> None:
    if not matches:
        print("No relevant Anvil memory found.")
        return
    for score, item in matches[:limit]:
        source = item.get("source", {})
        body = re.sub(r"\s+", " ", item.get("body", "")).strip()
        if len(body) > 420:
            body = body[:417].rstrip() + "..."
        print(f"[{item.get('id', 'unknown')}] {item.get('type', '?')} / {item.get('scope', '?')} (match {score})")
        print(f"  status: {item.get('status', 'unspecified')}; confidence: {item.get('confidence', 'unspecified')}; source: {source.get('type', 'unspecified')}")
        if item.get("id") in (stale_ids or set()):
            print("  freshness: potentially stale; a registered source changed or is missing")
        if item.get("aliases"):
            print(f"  aliases: {', '.join(item['aliases'][:5])}")
        for key in ("path", "url", "commit", "section", "sha256", "note"):
            if source.get(key):
                print(f"  {key}: {source[key]}")
        if item.get("evidence"):
            print(f"  evidence: {'; '.join(item['evidence'][:3])}")
        print(f"  file: {item['path']}")
        print(f"  {body}")


def folder_for(kind: str, scope: str, entry_id: str) -> Path:
    if scope == "company":
        return Path("company")
    if scope.startswith("project:"):
        project = slug(scope.split(":", 1)[1])
        return Path("projects") / project
    if kind == "project" or scope == "project":
        return Path("projects") / "general"
    if kind == "decision":
        return Path("decisions")
    if kind == "lesson":
        return Path("lessons")
    return Path("company")


def validate_entry(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("input must be a JSON object")
    required = {"id", "type", "scope", "tags", "source", "confidence", "body"}
    optional = {"aliases", "status", "evidence"}
    if set(raw) - required - optional:
        raise ValueError("unsupported fields: " + ", ".join(sorted(set(raw) - required - optional)))
    missing = required - raw.keys()
    if missing:
        raise ValueError("missing fields: " + ", ".join(sorted(missing)))
    if raw["type"] not in MEMORY_TYPES:
        raise ValueError("type must be fact, decision, lesson, or project")
    if not isinstance(raw["scope"], str) or not re.fullmatch(r"(?:company|project(?::[A-Za-z0-9_. -]+)?)", raw["scope"]):
        raise ValueError("scope must be company, project, or project:<name>")
    if not isinstance(raw["tags"], list) or len(raw["tags"]) > 16:
        raise ValueError("tags must be an array with at most 16 items")
    tags = []
    for tag in raw["tags"]:
        if not isinstance(tag, str):
            raise ValueError("each tag must be text")
        tags.append(slug(tag, max_length=40))
    source = raw["source"]
    if not isinstance(source, dict) or set(source) - SOURCE_FIELDS:
        raise ValueError("source must be an object with type, path, url, commit, or note fields")
    if source.get("type") not in SOURCE_TYPES:
        raise ValueError("source.type must identify user-explicit, repository, document, url, commit, test, or other")
    for key, value in source.items():
        if not isinstance(value, str) or len(value) > 1000:
            raise ValueError(f"source.{key} must be text of at most 1000 characters")
    if raw["confidence"] not in CONFIDENCE:
        raise ValueError("confidence must be confirmed, high, medium, low, or unverified")
    status = raw.get("status")
    if status is not None and status not in STATUSES:
        raise ValueError("status must be sourced, corroborated, conflicted, historical, or uncertain")
    aliases = raw.get("aliases", [])
    if not isinstance(aliases, list) or len(aliases) > 24 or any(not isinstance(alias, str) or not alias.strip() or len(alias) > 120 for alias in aliases):
        raise ValueError("aliases must be an array of at most 24 short text values")
    evidence = raw.get("evidence", [])
    if not isinstance(evidence, list) or len(evidence) > 24 or any(not isinstance(item, str) or not item.strip() or len(item) > 1000 for item in evidence):
        raise ValueError("evidence must be an array of at most 24 short text values")
    if not isinstance(raw["body"], str) or not raw["body"].strip() or len(raw["body"]) > 20000:
        raise ValueError("body must contain 1 to 20000 characters")
    body = raw["body"].replace("\r\n", "\n").replace("\r", "\n").strip()
    return {
        "id": slug(str(raw["id"])), "type": raw["type"], "scope": raw["scope"],
        "tags": list(dict.fromkeys(tags)), "aliases": list(dict.fromkeys(a.strip() for a in aliases)),
        "source": source, "confidence": raw["confidence"], "status": status,
        "evidence": list(dict.fromkeys(e.strip() for e in evidence)), "body": body,
    }


def frontmatter(data: dict[str, Any], created: str, updated: str) -> str:
    lines = ["---"]
    for key in ("id", "type", "scope"):
        lines.append(f"{key}: {quote_yaml(data[key])}")
    lines.append("tags:")
    lines.extend(f"  - {quote_yaml(tag)}" for tag in data["tags"])
    if data.get("aliases"):
        lines.append("aliases:")
        lines.extend(f"  - {quote_yaml(alias)}" for alias in data["aliases"])
    lines.append("source:")
    for key in ("type", "path", "url", "commit", "note"):
        if key in data["source"]:
            lines.append(f"  {key}: {quote_yaml(data['source'][key])}")
    for key in sorted(set(data["source"]) - {"type", "path", "url", "commit", "note"}):
        lines.append(f"  {key}: {quote_yaml(data['source'][key])}")
    lines.append(f"confidence: {quote_yaml(data['confidence'])}")
    if data.get("status"):
        lines.append(f"status: {quote_yaml(data['status'])}")
    if data.get("evidence"):
        lines.append("evidence:")
        lines.extend(f"  - {quote_yaml(item)}" for item in data["evidence"])
    lines.extend([
        f"created: {created}",
        f"updated: {updated}",
        "---",
        "",
        data["body"],
        "",
    ])
    return "\n".join(lines)


def duplicate_candidate(data: dict[str, Any], root: Path) -> dict[str, Any] | None:
    words = set(re.findall(r"[a-z0-9][a-z0-9_-]{2,}", data["body"].lower()))
    words.update(data["tags"])
    if len(words) < 4:
        return None
    best: tuple[float, dict[str, Any]] | None = None
    for item in entries(root):
        existing = set(re.findall(r"[a-z0-9][a-z0-9_-]{2,}", item.get("body", "").lower()))
        existing.update(item.get("tags", []))
        overlap = len(words & existing)
        ratio = overlap / max(1, min(len(words), len(existing)))
        if overlap >= 4 and ratio >= 0.82 and item.get("id") != data["id"]:
            if best is None or ratio > best[0]:
                best = ratio, item
    return best[1] if best else None


def write_entry(data: dict[str, Any], root: Path) -> tuple[Path, bool]:
    base = root / folder_for(data["type"], data["scope"], data["id"])
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    target = base / f"{data['id']}.md"
    if not target.exists():
        duplicate = duplicate_candidate(data, root)
        if duplicate:
            raise ValueError(
                f"possible duplicate '{duplicate.get('id')}' at {duplicate['path']}; search and reuse that id to update it"
            )
    updated_entry = target.is_file()
    created = date.today().isoformat()
    if updated_entry:
        match = re.search(r"(?m)^created:\s*(\d{4}-\d{2}-\d{2})\s*$", target.read_text(encoding="utf-8"))
        if match:
            created = match.group(1)
    text = frontmatter(data, created, date.today().isoformat())
    fd, temporary = tempfile.mkstemp(prefix=f".{data['id']}.", suffix=".tmp", dir=base)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    os.chmod(target, 0o600)
    return target, updated_entry


def main() -> int:
    parser = argparse.ArgumentParser(description="Search Anvil memory or persist an explicitly requested entry")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("init", help="create the empty memory, knowledge, and source registry layout")
    p_search = sub.add_parser("search")
    p_search.add_argument("query", nargs="+")
    p_recall = sub.add_parser("recall")
    p_recall.add_argument("query", nargs="+")
    p_recall.add_argument("--limit", type=int, default=5)
    p_write = sub.add_parser("write-json", help="write one entry from JSON on stdin; never called automatically")
    p_write.add_argument("--allow-duplicate", action="store_true", help="allow a matching entry after explicit review")
    p_check = sub.add_parser("check")
    p_audit = sub.add_parser("audit", help="report valid and invalid Markdown memory files as JSON")
    p_tool = sub.add_parser("tool-search", help="bounded JSON search for the Anvil core plugin")
    p_tool.add_argument("query")
    p_tool.add_argument("--scope")
    p_tool.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    root = memory_root()
    if args.action == "init":
        for directory in (root / "company", root / "projects", root / "decisions", root / "lessons"):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(directory, 0o700)
        os.chmod(root, 0o700)
        for directory in (data_root() / "knowledge", data_root() / "sources"):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(directory, 0o700)
        print(root)
        return 0
    if args.action == "audit":
        print(json.dumps(audit(root)))
        return 0
    if args.action == "check":
        try:
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(root, 0o700)
            count = len(entries(root))
            probe = root / ".anvil-write-check"
            probe.write_text("ok\n", encoding="utf-8")
            probe.unlink()
            print(count)
            return 0
        except OSError as exc:
            print(f"memory is not readable/writable: {exc}", file=sys.stderr)
            return 1
    if args.action == "tool-search":
        query = args.query.strip()
        if not query or len(query) > 500:
            print(json.dumps({"results": [], "message": "Query must contain 1 to 500 characters."}))
            return 0
        limit = max(1, min(args.limit, 5))
        matches = scored_matches(root, query)
        stale_ids = stale_memory_ids()
        results = []
        for score, item in matches:
            if args.scope and item.get("scope") != args.scope:
                continue
            source = item.get("source", {})
            excerpt = re.sub(r"\s+", " ", item.get("body", "")).strip()
            results.append({
                "id": item.get("id"), "type": item.get("type"), "scope": item.get("scope"),
                "status": item.get("status"), "confidence": item.get("confidence"),
                "potentially_stale": item.get("id") in stale_ids,
                "source": {key: source[key] for key in ("type", "path", "url", "commit", "section", "sha256") if source.get(key)},
                "relevance": score, "excerpt": excerpt[:240], "path": item.get("path"),
            })
            if len(results) >= limit:
                break
        print(json.dumps({"results": results}, ensure_ascii=False))
        return 0
    if args.action in ("search", "recall"):
        query = " ".join(args.query).strip()
        matches = scored_matches(root, query)
        show_matches(matches, 10 if args.action == "search" else max(1, min(args.limit, 10)), stale_memory_ids())
        return 0 if matches else 1
    try:
        raw = json.load(sys.stdin)
        data = validate_entry(raw)
        target, _ = write_entry(data, root)
        print(f"Wrote {target}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
