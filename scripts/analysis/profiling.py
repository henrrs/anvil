"""Bounded, deterministic profiling for explicitly named local tables."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .errors import AnalysisError
from .semantic import infer_semantic_context


MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 200
MAX_PROFILE_CELLS = 250_000
MAX_DISTINCT_TRACKED = 2_000


def _has_symlink(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not value:
        return "0"
    return format(value.normalize(), "f")


def _coerce(value: Any) -> Any:
    if isinstance(value, Decimal):
        if len(value.as_tuple().digits) > 1000 or abs(value.adjusted()) > 1000:
            return str(value)
        return value
    if value is None or isinstance(value, (bool, date, datetime)):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    if len(text) > 1024:
        return text
    if text.casefold() in {"true", "false"}:
        return text.casefold() == "true"
    # Preserve common identifier encodings such as 0017 instead of turning them into 17.
    if not re.fullmatch(r"[+-]?0\d+", text):
        try:
            number = Decimal(text)
            if number.is_finite():
                if len(number.as_tuple().digits) <= 1000 and abs(number.adjusted()) <= 1000:
                    return number
                return text
        except InvalidOperation:
            pass
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            pass
    if re.fullmatch(r"\d{4}-\d{2}", text):
        try:
            return date.fromisoformat(text + "-01")
        except ValueError:
            pass
    if "T" in text:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            pass
    return text


def _json_number(value: str) -> Decimal:
    if len(value) > 1024:
        raise AnalysisError("INPUT_LIMIT_EXCEEDED", "A JSON numeric value exceeds the supported precision/magnitude token limit.")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise AnalysisError("INPUT_SCHEMA_INVALID", "JSON contains an invalid numeric value.") from None
    if len(number.as_tuple().digits) > 1000 or abs(number.adjusted()) > 1000:
        raise AnalysisError("INPUT_LIMIT_EXCEEDED", "A JSON numeric value exceeds the supported precision/magnitude limit.")
    return number


def _reject_json_constant(value: str) -> Any:
    raise AnalysisError("INPUT_SCHEMA_INVALID", f"JSON non-finite numeric constant {value!r} is not supported.")


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise AnalysisError("INPUT_SCHEMA_INVALID", f"JSON object contains a duplicate field name: {key!r}.")
        value[key] = item
    return value


def _json_decoder() -> json.JSONDecoder:
    return json.JSONDecoder(parse_float=_json_number, parse_int=_json_number,
                            parse_constant=_reject_json_constant, object_pairs_hook=_json_object)


def _validate_flat_row(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AnalysisError("INPUT_SCHEMA_INVALID", f"{label} must be a flat row object.")
    for name, cell in value.items():
        if not isinstance(name, str) or not name.strip() or len(name) > 240:
            raise AnalysisError("INPUT_SCHEMA_INVALID", "JSON field names must be non-empty text of at most 240 characters.")
        if isinstance(cell, (dict, list)):
            raise AnalysisError("INPUT_SCHEMA_UNSUPPORTED", "Nested JSON objects/arrays are not treated as flat table cells; extract the relevant fields first.")
    return value


def _check_profile_cells(row_count: int, column_count: int) -> None:
    if row_count * column_count > MAX_PROFILE_CELLS:
        raise AnalysisError("INPUT_LIMIT_EXCEEDED", f"Profile would exceed the {MAX_PROFILE_CELLS:,}-cell working limit.",
                            remediation="Use fewer columns or a narrower/pre-aggregated local extract.")


def _read(path_value: str | Path, *, max_rows: int = MAX_ROWS) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = Path(os.path.abspath(Path(path_value).expanduser()))
    if not 1 <= max_rows <= MAX_ROWS:
        raise AnalysisError("ANALYSIS_BUDGET_EXCEEDED", f"max_rows must be between 1 and {MAX_ROWS}.")
    if _has_symlink(path):
        raise AnalysisError("INPUT_UNSAFE", "Analysis input path contains a symbolic link; links are not followed.")
    try:
        before = path.stat()
    except OSError:
        raise AnalysisError("INPUT_UNREADABLE", "The explicitly named analysis input is not readable.") from None
    if not path.is_file():
        raise AnalysisError("INPUT_UNREADABLE", "Analysis input must be an explicitly named regular file.")
    if before.st_size > MAX_SOURCE_BYTES:
        raise AnalysisError("INPUT_LIMIT_EXCEEDED", f"Input exceeds the {MAX_SOURCE_BYTES // (1024 * 1024)} MiB analysis limit.",
                            remediation="Use a narrower or pre-aggregated local extract.")
    suffix = path.suffix.casefold()
    if suffix not in {".csv", ".tsv", ".json", ".jsonl", ".ndjson"}:
        raise AnalysisError("INPUT_FORMAT_UNSUPPORTED", "Supported local table formats are CSV, TSV, JSON arrays, and JSON Lines.")
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_SOURCE_BYTES:
            raise AnalysisError("INPUT_LIMIT_EXCEEDED", "Input grew beyond the configured byte limit while reading.")
        content = raw.decode("utf-8-sig")
    except (OSError, UnicodeError):
        raise AnalysisError("INPUT_UNREADABLE", "Analysis input must be readable UTF-8 text.") from None
    if len(raw) != before.st_size:
        raise AnalysisError("INPUT_SOURCE_CHANGED", "Input size changed while being read; retry after it stops changing.")

    try:
        if suffix in {".csv", ".tsv"}:
            delimiter = "\t" if suffix == ".tsv" else ","
            reader = csv.reader(io.StringIO(content, newline=""), delimiter=delimiter, strict=True)
            header = next(reader, None)
            if not header or len(header) > MAX_COLUMNS or any(not name.strip() or len(name) > 240 for name in header):
                raise AnalysisError("INPUT_SCHEMA_INVALID", f"Delimited input needs 1 to {MAX_COLUMNS} non-empty column names.")
            if len(set(header)) != len(header):
                raise AnalysisError("INPUT_SCHEMA_INVALID", "Delimited input column names must be unique.")
            rows: list[dict[str, Any]] = []
            row_count = 0
            for values in reader:
                if len(values) != len(header):
                    raise AnalysisError("INPUT_SCHEMA_INVALID", f"Row {row_count + 2} has a different number of fields than the header.")
                row_count += 1
                if len(rows) < max_rows:
                    _check_profile_cells(len(rows) + 1, len(header))
                    rows.append({name: _coerce(value) for name, value in zip(header, values)})
            columns = header
        elif suffix == ".json":
            decoder = _json_decoder()
            index = len(content) - len(content.lstrip())
            if index >= len(content) or content[index] != "[":
                raise AnalysisError("INPUT_SCHEMA_INVALID", "JSON input must be an array of row objects.")
            index += 1
            rows = []
            row_count = 0
            columns_set: set[str] = set()
            while True:
                while index < len(content) and content[index].isspace():
                    index += 1
                if index < len(content) and content[index] == "]":
                    index += 1
                    break
                try:
                    value, index = decoder.raw_decode(content, index)
                except json.JSONDecodeError:
                    raise AnalysisError("INPUT_SCHEMA_INVALID", "Input is malformed or has inconsistent row structure.") from None
                value = _validate_flat_row(value, label="JSON array record")
                columns_set.update(value)
                if len(columns_set) > MAX_COLUMNS:
                    raise AnalysisError("INPUT_LIMIT_EXCEEDED", f"JSON input exceeds {MAX_COLUMNS} distinct fields.")
                row_count += 1
                _check_profile_cells(min(row_count, max_rows), len(columns_set))
                if row_count <= max_rows:
                    rows.append(value)
                while index < len(content) and content[index].isspace():
                    index += 1
                if index < len(content) and content[index] == ",":
                    index += 1
                    while index < len(content) and content[index].isspace():
                        index += 1
                    if index >= len(content) or content[index] == "]":
                        raise AnalysisError("INPUT_SCHEMA_INVALID", "JSON array has a missing row after a comma.")
                    continue
                if index < len(content) and content[index] == "]":
                    index += 1
                    break
                raise AnalysisError("INPUT_SCHEMA_INVALID", "JSON array rows must be separated by commas.")
            if content[index:].strip():
                raise AnalysisError("INPUT_SCHEMA_INVALID", "JSON input contains data after the row array.")
            columns = sorted(columns_set)
            if not columns or len(columns) > MAX_COLUMNS:
                raise AnalysisError("INPUT_SCHEMA_INVALID", f"JSON input needs 1 to {MAX_COLUMNS} distinct fields.")
            _check_profile_cells(len(rows), len(columns))
            rows = [{name: _coerce(row.get(name)) for name in columns} for row in rows]
        else:
            rows = []
            row_count = 0
            columns_set: set[str] = set()
            decoder = _json_decoder()
            for line_number, line in enumerate(io.StringIO(content), 1):
                if not line.strip():
                    continue
                try:
                    value = decoder.decode(line)
                except json.JSONDecodeError:
                    raise AnalysisError("INPUT_SCHEMA_INVALID", f"JSON Lines record {line_number} is malformed.") from None
                value = _validate_flat_row(value, label=f"JSON Lines record {line_number}")
                columns_set.update(value)
                if len(columns_set) > MAX_COLUMNS:
                    raise AnalysisError("INPUT_LIMIT_EXCEEDED", f"JSON Lines input exceeds {MAX_COLUMNS} distinct fields.")
                row_count += 1
                _check_profile_cells(min(row_count, max_rows), len(columns_set))
                if row_count <= max_rows:
                    rows.append(value)
            columns = sorted(columns_set)
            if not columns:
                raise AnalysisError("INPUT_SCHEMA_INVALID", "JSON Lines input has no fields.")
            _check_profile_cells(len(rows), len(columns))
            rows = [{name: _coerce(row.get(name)) for name in columns} for row in rows]
    except AnalysisError:
        raise
    except (csv.Error, json.JSONDecodeError, ValueError, TypeError):
        raise AnalysisError("INPUT_SCHEMA_INVALID", "Input is malformed or has inconsistent row structure.") from None
    try:
        after = path.stat()
    except OSError:
        raise AnalysisError("INPUT_SOURCE_CHANGED", "Input became unavailable while it was read.") from None
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise AnalysisError("INPUT_SOURCE_CHANGED", "Input changed while it was being analyzed; retry after it stops changing.")
    source = {"type": suffix.lstrip("."), "locator": str(path),
              "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
    return rows, {"source": source, "columns": columns, "row_count": row_count,
                  "rows_available": len(rows), "truncated": row_count > len(rows)}


def _type_name(values: list[Any]) -> str:
    types = {"boolean" if isinstance(value, bool) else
             "number" if isinstance(value, (int, Decimal)) and not isinstance(value, bool) else
             "datetime" if isinstance(value, datetime) else
             "date" if isinstance(value, date) else "string" for value in values if value is not None}
    if not types:
        return "unknown"
    if types <= {"number"}:
        return "number"
    if types <= {"date", "datetime"}:
        return "temporal"
    if len(types) == 1:
        return next(iter(types))
    return "mixed"


def profile_file(path: str | Path, *, max_rows: int = MAX_ROWS,
                 semantic_depth: str = "STANDARD", semantic_focus: str = "general",
                 semantic_metadata: Any = None) -> dict[str, Any]:
    rows, metadata = _read(path, max_rows=max_rows)
    columns = []
    for name in metadata["columns"]:
        values = [row.get(name) for row in rows]
        present = [value for value in values if value is not None]
        distinct: set[Any] = set()
        exact = True
        for value in present:
            try:
                distinct.add(value)
            except TypeError:
                distinct.add(json.dumps(value, sort_keys=True, default=str))
            if len(distinct) > MAX_DISTINCT_TRACKED:
                exact = False
                distinct.clear()
                break
        kind = _type_name(values)
        numeric = [value for value in present if isinstance(value, (int, Decimal)) and not isinstance(value, bool)]
        temporal = [value for value in present if isinstance(value, (date, datetime))]
        null_count = len(values) - len(present)
        item: dict[str, Any] = {
            "name": name, "inferred_type": kind, "profiled_values": len(values),
            "null_count": null_count,
            "null_rate": _decimal_text(Decimal(null_count) / Decimal(len(values))) if values else None,
            "distinct_count": len(distinct) if exact else None,
            "distinct_count_exact": exact,
        }
        if numeric:
            item["numeric"] = {"min": _decimal_text(min(numeric)), "max": _decimal_text(max(numeric)),
                                "sum": _decimal_text(sum(numeric, Decimal(0))),
                                "mean": _decimal_text(sum(numeric, Decimal(0)) / Decimal(len(numeric))),
                                "observed_count": len(numeric)}
        if temporal:
            temporal_text = sorted(value.isoformat() for value in temporal)
            item["temporal"] = {"min": temporal_text[0], "max": temporal_text[-1],
                                "observed_count": len(temporal)}
        item["candidate_roles"] = _candidate_roles(name, kind, len(present), len(distinct) if exact else None,
                                                  len(values), null_count)
        columns.append(item)
    complete = not metadata["truncated"]
    profile = {
        "schema_version": 1, "profile_id": "PROFILE-" + metadata["source"]["sha256"][:12],
        "source": metadata["source"], "row_count": metadata["row_count"],
        "profiled_rows": len(rows), "column_count": len(columns), "columns": columns,
        "statistics_scope": "sampled_prefix" if metadata["truncated"] else "complete",
        "limitations": ([f"Only the first {len(rows)} rows were profiled; row_count is exact but column statistics may not represent later rows."]
                        if metadata["truncated"] else []),
        "limits": {"max_source_bytes": MAX_SOURCE_BYTES, "max_profile_rows": max_rows,
                   "max_profile_cells": MAX_PROFILE_CELLS,
                   "max_columns": MAX_COLUMNS, "max_distinct_values_tracked": MAX_DISTINCT_TRACKED},
    }
    profile["semantic_context"] = infer_semantic_context(
        rows, metadata["columns"], total_rows=metadata["row_count"], complete=complete,
        depth=semantic_depth, focus=semantic_focus, semantic_metadata=semantic_metadata)
    return profile


def load_rows(path: str | Path, *, max_rows: int = 50_000) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return _read(path, max_rows=max_rows)


def _candidate_roles(name: str, kind: str, present: int, distinct: int | None, rows: int, null_count: int) -> list[str]:
    roles = []
    normalized_name = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")
    if kind == "temporal":
        roles.append("temporal_dimension")
    if kind == "number":
        roles.append("measure")
        if any(token in normalized_name.split("_") for token in ("rate", "ratio", "percent", "percentage", "pct", "share")):
            roles.append("candidate_rate")
        if normalized_name.split("_")[-1] in {"count", "total"}:
            roles.append("candidate_count")
    if kind in {"string", "boolean"}:
        roles.append("dimension")
    if present and distinct is not None and distinct >= 0.95 * rows and null_count == 0:
        roles.append("candidate_identifier")
    if distinct is not None and distinct <= 50 and present:
        roles.append("candidate_segment")
    return roles or ["unknown"]
