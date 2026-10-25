"""Explicit, bounded input discovery and text extraction adapters."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import posixpath
import re
import resource
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Iterator

from .errors import CommunicationError


SUPPORTED = {
    ".md": "markdown", ".markdown": "markdown", ".txt": "text", ".rst": "text",
    ".csv": "csv", ".tsv": "tsv", ".json": "json", ".jsonc": "jsonc-text",
    ".py": "source", ".sql": "source", ".sh": "source", ".ts": "source", ".tsx": "source",
    ".js": "source", ".jsx": "source", ".java": "source", ".scala": "source",
    ".go": "source", ".rs": "source", ".yml": "configuration", ".yaml": "configuration",
    ".toml": "configuration", ".ini": "configuration", ".cfg": "configuration", ".conf": "configuration",
    ".docx": "docx", ".pptx": "pptx", ".xlsx": "xlsx", ".pdf": "pdf",
}
EXCLUDED_DIRS = {".git", ".venv", "venv", "node_modules", "dist", "build", "target", "coverage", "__pycache__"}
MAX_FILES = 200
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_EXTRACTED_BYTES = 512 * 1024
MAX_ARCHIVE_ENTRIES = 2000
MAX_ARCHIVE_EXPANDED_BYTES = 32 * 1024 * 1024


def _iter_directory(root: Path, recursive: bool) -> Iterator[Path]:
    if not recursive:
        yield from sorted((item for item in root.iterdir() if not item.is_symlink()), key=lambda item: item.name.casefold())
        return
    for directory, names, filenames in os.walk(root, followlinks=False):
        names[:] = sorted(name for name in names if name not in EXCLUDED_DIRS
                          and not (Path(directory) / name).is_symlink())
        for name in sorted(filenames, key=str.casefold):
            path = Path(directory) / name
            if not path.is_symlink():
                yield path


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current = current / component
        if current.is_symlink():
            return True
    return False


def _source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(128 * 1024):
                total += len(chunk)
                if total > MAX_SOURCE_BYTES:
                    raise CommunicationError("INPUT_LIMIT_EXCEEDED", f"{path.name} exceeds the source file size limit.")
                digest.update(chunk)
    except OSError:
        raise CommunicationError("INPUT_UNREADABLE", f"Could not read source metadata for {path.name}.") from None
    return digest.hexdigest()


def discover(sources: list[str], *, recursive: bool = False, max_files: int = MAX_FILES) -> dict[str, Any]:
    if not sources or not 1 <= max_files <= MAX_FILES:
        raise CommunicationError("CONTRACT_INVALID", f"Name at least one source and keep max_files between 1 and {MAX_FILES}.")
    distinct: dict[str, Path] = {}
    ignored: list[dict[str, str]] = []

    def add(path: Path) -> None:
        absolute = str(path.absolute())
        if absolute not in distinct:
            distinct[absolute] = path
            if len(distinct) > max_files:
                raise CommunicationError("INPUT_LIMIT_EXCEEDED", f"Input discovery exceeded the {max_files} file limit.",
                                         remediation="Name fewer files or use a narrower input directory.")

    for raw in sources:
        path = Path(os.path.abspath(Path(raw).expanduser()))
        if _has_symlink_component(path):
            ignored.append({"path": str(path), "reason": "symbolic links are not followed"})
        elif path.is_file():
            add(path)
        elif path.is_dir():
            for item in _iter_directory(path, recursive):
                if item.is_file():
                    add(item)
        else:
            ignored.append({"path": str(path), "reason": "source does not exist or is not a regular file/directory"})
    files = sorted(distinct.values(), key=lambda item: str(item).casefold())
    found = []
    for path in files:
        kind = SUPPORTED.get(path.suffix.casefold())
        if kind is None:
            ignored.append({"path": str(path), "reason": "unsupported file type"})
            continue
        try:
            before = path.stat()
        except OSError:
            ignored.append({"path": str(path), "reason": "source became unavailable during discovery"})
            continue
        size = before.st_size
        if size > MAX_SOURCE_BYTES:
            ignored.append({"path": str(path), "reason": f"source exceeds {MAX_SOURCE_BYTES} byte analysis limit"})
            continue
        digest = _source_hash(path)
        after = path.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise CommunicationError("INPUT_SOURCE_CHANGED", f"{path.name} changed while its source inventory was being hashed.",
                                     remediation="Retry discovery after the source has stopped changing.")
        found.append({"id": "SRC-" + digest[:12], "path": str(path), "name": path.name,
                      "type": kind, "suffix": path.suffix.casefold(), "size_bytes": size,
                      "sha256": digest, "read_mode": "targeted extraction required",
                      "provenance": {"locator": str(path), "sha256": digest}})
    return {"schema_version": 1, "recursive": recursive, "sources": found, "ignored": ignored,
            "limits": {"max_files": max_files, "max_source_bytes": MAX_SOURCE_BYTES,
                       "max_extracted_bytes": MAX_EXTRACTED_BYTES}}


def _decode(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CommunicationError("INPUT_FORMAT_UNSUPPORTED", f"{path.name} is not valid UTF-8 text.",
                                 remediation="Use an explicitly supported text encoding or convert the file locally.") from None


def _zip_members(path: Path) -> zipfile.ZipFile:
    archive = zipfile.ZipFile(path, "r")
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES or sum(item.file_size for item in infos) > MAX_ARCHIVE_EXPANDED_BYTES:
        archive.close()
        raise CommunicationError("INPUT_LIMIT_EXCEEDED", f"{path.name} archive exceeds the bounded OOXML extraction limit.")
    if any(item.file_size > MAX_SOURCE_BYTES for item in infos):
        archive.close()
        raise CommunicationError("INPUT_LIMIT_EXCEEDED", f"{path.name} contains an oversized archive member.")
    return archive


def _xml_root(archive: zipfile.ZipFile, name: str) -> ET.Element:
    try:
        raw = archive.read(name)
    except KeyError:
        raise CommunicationError("INPUT_FORMAT_UNSUPPORTED", f"OOXML member {name} is missing.") from None
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise CommunicationError("INPUT_FORMAT_UNSUPPORTED", "OOXML documents with custom entity declarations are not read.")
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        raise CommunicationError("INPUT_UNREADABLE", f"OOXML member {name} is malformed.") from None


def _extract_docx(path: Path) -> tuple[str, list[str]]:
    with _zip_members(path) as archive:
        root = _xml_root(archive, "word/document.xml")
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs = []
        for paragraph in root.findall(".//w:p", namespace):
            text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace))
            if text.strip():
                paragraphs.append(text)
        return "\n".join(paragraphs), [f"{len(paragraphs)} paragraphs extracted; embedded media not inspected."]


def _extract_pptx(path: Path) -> tuple[str, list[str]]:
    with _zip_members(path) as archive:
        names = set(archive.namelist())
        slide_parts: list[str] = []
        if "ppt/presentation.xml" in names and "ppt/_rels/presentation.xml.rels" in names:
            presentation = _xml_root(archive, "ppt/presentation.xml")
            relationships = _xml_root(archive, "ppt/_rels/presentation.xml.rels")
            p_ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
                    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
            rel_ns = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
            targets = {item.get("Id"): item for item in relationships.findall("rel:Relationship", rel_ns)}
            for slide_id in presentation.findall(".//p:sldIdLst/p:sldId", p_ns):
                relationship = targets.get(slide_id.get(f"{{{p_ns['r']}}}id"))
                if relationship is None or relationship.get("TargetMode") == "External":
                    raise CommunicationError("INPUT_UNREADABLE", "Presentation slide order references a missing or external slide part.")
                target = relationship.get("Target", "")
                part = posixpath.normpath(posixpath.join("ppt", target))
                if not part.startswith("ppt/slides/") or part not in names:
                    raise CommunicationError("INPUT_UNREADABLE", "Presentation slide relationship points outside the slide parts.")
                slide_parts.append(part)
            if len(slide_parts) != len(set(slide_parts)):
                raise CommunicationError("INPUT_UNREADABLE", "Presentation slide order contains duplicate slide parts.")
        else:
            numbered = sorted((name for name in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
                              key=lambda name: int(re.search(r"slide(\d+)", name).group(1)))
            slide_parts.extend(numbered)
        slides = []
        for number, name in enumerate(slide_parts, 1):
            root = _xml_root(archive, name)
            namespace = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
            text = " ".join(node.text or "" for node in root.findall(".//a:t", namespace)).strip()
            if text:
                slides.append(f"[Slide {number}] {text}")
        notes = [f"{len(slide_parts)} slide XML parts read in declared presentation order; images, charts, speaker notes, and embedded objects not inspected."]
        return "\n".join(slides), notes


def _extract_xlsx(path: Path, row_limit: int = 200) -> tuple[str, list[str]]:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    with _zip_members(path) as archive:
        names = set(archive.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = _xml_root(archive, "xl/sharedStrings.xml")
            shared = ["".join(node.text or "" for node in item.findall(".//m:t", ns)) for item in root.findall("m:si", ns)]
        sheets = sorted((name for name in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)),
                        key=lambda item: int(re.search(r"sheet(\d+)", item).group(1)))
        chunks = []
        notes = []
        for sheet_index, name in enumerate(sheets, 1):
            root = _xml_root(archive, name)
            rows = []
            for row_index, row in enumerate(root.findall(".//m:sheetData/m:row", ns)):
                if row_index >= row_limit:
                    notes.append(f"{name}: row extraction capped at {row_limit}.")
                    break
                cells = []
                for cell in row.findall("m:c", ns):
                    ref = cell.get("r", "")
                    value_node = cell.find("m:v", ns)
                    value = value_node.text if value_node is not None else ""
                    if cell.get("t") == "s" and value:
                        try:
                            value = shared[int(value)]
                        except (ValueError, IndexError):
                            value = "[invalid shared string index]"
                    inline = cell.find("m:is", ns)
                    if inline is not None:
                        value = "".join(node.text or "" for node in inline.findall(".//m:t", ns))
                    cells.append(f"{ref}={value}")
                if cells:
                    rows.append(" | ".join(cells))
            chunks.append(f"[Worksheet {sheet_index}: {name}]\n" + "\n".join(rows))
        notes.append("Workbook formulas are not recalculated; date styles, charts, and embedded media are not interpreted.")
        return "\n\n".join(chunks), notes


def _extract_pdf(path: Path) -> tuple[str, list[str]]:
    executable = shutil.which("pdftotext")
    if not executable:
        raise CommunicationError("RENDERER_UNAVAILABLE", "PDF text extraction requires the optional pdftotext utility.",
                                 remediation="Use Markdown/text/OOXML inputs or install pdftotext outside Anvil.")
    try:
        with tempfile.TemporaryFile(mode="w+b") as output:
            file_limit = MAX_EXTRACTED_BYTES + 1
            def limit_child_output() -> None:
                resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))
            result = subprocess.run([executable, "-layout", str(path), "-"], stdout=output,
                                    stderr=subprocess.DEVNULL, timeout=30, check=False,
                                    preexec_fn=limit_child_output)
            output.seek(0)
            raw = output.read(MAX_EXTRACTED_BYTES + 1)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise CommunicationError("INPUT_UNREADABLE", f"Text extraction did not complete for {path.name}.") from None
    if result.returncode and len(raw) <= MAX_EXTRACTED_BYTES:
        raise CommunicationError("INPUT_UNREADABLE", f"PDF text extraction failed for {path.name}.")
    notes = ["Text layer extracted; scanned images and OCR were not inspected."]
    if len(raw) > MAX_EXTRACTED_BYTES:
        raw = raw[:MAX_EXTRACTED_BYTES]
        notes.append(f"PDF text extraction capped at {MAX_EXTRACTED_BYTES} bytes.")
    return raw.decode("utf-8", errors="replace"), notes


def extract(path_text: str, *, max_bytes: int = MAX_EXTRACTED_BYTES,
            start_line: int | None = None, end_line: int | None = None) -> dict[str, Any]:
    path = Path(os.path.abspath(Path(path_text).expanduser()))
    if _has_symlink_component(path) or not path.is_file():
        raise CommunicationError("INPUT_UNREADABLE", "Input must be an explicitly named regular file; symbolic links are not followed.")
    if not 1 <= max_bytes <= MAX_EXTRACTED_BYTES:
        raise CommunicationError("INPUT_LIMIT_EXCEEDED", f"max_bytes must be between 1 and {MAX_EXTRACTED_BYTES}.")
    initial_stat = path.stat()
    if initial_stat.st_size > MAX_SOURCE_BYTES:
        raise CommunicationError("INPUT_LIMIT_EXCEEDED", f"{path.name} exceeds the source file size limit.")
    digest_before = _source_hash(path)
    suffix = path.suffix.casefold()
    kind = SUPPORTED.get(suffix)
    if kind is None:
        raise CommunicationError("INPUT_FORMAT_UNSUPPORTED", f"Input type {suffix or '(none)'} is not supported.")
    notes: list[str] = []
    if kind == "docx":
        text, notes = _extract_docx(path)
    elif kind == "pptx":
        text, notes = _extract_pptx(path)
    elif kind == "xlsx":
        text, notes = _extract_xlsx(path)
    elif kind == "pdf":
        text, notes = _extract_pdf(path)
    elif kind in {"csv", "tsv"}:
        delimiter = "\t" if kind == "tsv" else ","
        rows = []
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                for index, row in enumerate(csv.reader(stream, delimiter=delimiter)):
                    if index >= 201:
                        notes.append("Tabular text capped at 200 data rows plus a header/preview row.")
                        break
                    rows.append(" | ".join(row))
        except (OSError, UnicodeError, csv.Error):
            raise CommunicationError("INPUT_UNREADABLE", f"Could not read delimited text from {path.name}.") from None
        text = "\n".join(rows)
    elif kind == "json":
        try:
            text = json.dumps(json.loads(_decode(path)), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            raise CommunicationError("INPUT_UNREADABLE", f"JSON source {path.name} is malformed.") from None
    else:
        text = _decode(path)

    if start_line is not None or end_line is not None:
        if kind not in {"markdown", "text", "source", "configuration", "jsonc-text"}:
            raise CommunicationError("INPUT_FORMAT_UNSUPPORTED", "Line-range extraction is available only for line-addressable text sources.")
        if start_line is None or end_line is None or start_line < 1 or end_line < start_line or end_line - start_line > 1000:
            raise CommunicationError("CONTRACT_INVALID", "Line range requires 1 <= start <= end and at most 1001 lines.")
        text = "\n".join(text.splitlines()[start_line - 1:end_line])
        notes.append(f"Lines {start_line}-{end_line} selected by explicit range.")
    encoded = text.encode("utf-8")
    truncated = len(encoded) > max_bytes
    if truncated:
        encoded = encoded[:max_bytes]
        text = encoded.decode("utf-8", errors="ignore")
        notes.append(f"Extraction truncated at {max_bytes} bytes; remaining content was not read into the result.")
    digest = _source_hash(path)
    final_stat = path.stat()
    if digest != digest_before or (initial_stat.st_dev, initial_stat.st_ino, initial_stat.st_size, initial_stat.st_mtime_ns) != (final_stat.st_dev, final_stat.st_ino, final_stat.st_size, final_stat.st_mtime_ns):
        raise CommunicationError("INPUT_SOURCE_CHANGED", f"{path.name} changed while it was being extracted; provenance is not stable.",
                                 remediation="Retry extraction after the source has stopped changing.")
    return {
        "schema_version": 1,
        "source": {"id": "SRC-" + digest[:12], "type": kind, "locator": str(path), "sha256": digest,
                   "size_bytes": initial_stat.st_size},
        "content": text,
        "truncated": truncated,
        "notes": notes,
        "content_lines": len(text.splitlines()),
    }
