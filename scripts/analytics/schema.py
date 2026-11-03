"""Canonical physical types shared by Parquet and DuckDB verification."""

from __future__ import annotations

import re
from typing import Any


def _parts(value: str) -> list[str]:
    result: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(value):
        if char in "([<":
            depth += 1
        elif char in ")]>":
            depth -= 1
        elif char == "," and depth == 0:
            result.append(value[start:index].strip())
            start = index + 1
    result.append(value[start:].strip())
    return result


def canonical_type(value: Any) -> str:
    """Normalize the certified Arrow/DuckDB type subset without lossy prefix matching."""
    if not isinstance(value, str):
        try:
            import pyarrow as pa
            kind = value
            if pa.types.is_string(kind) or pa.types.is_large_string(kind):
                return "string"
            if pa.types.is_boolean(kind):
                return "boolean"
            for name in ("int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64",
                         "float16", "float32", "float64"):
                if getattr(pa.types, "is_" + name, lambda _: False)(kind):
                    return {"float16": "float", "float32": "float", "float64": "double"}.get(name, name)
            if pa.types.is_decimal(kind):
                return f"decimal({kind.precision},{kind.scale})"
            if pa.types.is_date(kind):
                return "date"
            if pa.types.is_timestamp(kind):
                return "timestamp_tz" if kind.tz else "timestamp"
            if pa.types.is_binary(kind) or pa.types.is_large_binary(kind) or pa.types.is_fixed_size_binary(kind):
                return "binary"
            if pa.types.is_list(kind) or pa.types.is_large_list(kind) or pa.types.is_fixed_size_list(kind):
                return f"array<{canonical_type(kind.value_type)}>"
            if pa.types.is_map(kind):
                return f"map<{canonical_type(kind.key_type)},{canonical_type(kind.item_type)}>"
            if pa.types.is_struct(kind):
                return "struct<" + ",".join(
                    f"{field.name.casefold()}:{canonical_type(field.type)}"
                    for field in kind) + ">"
            if pa.types.is_null(kind):
                return "null"
        except ImportError:
            pass
        value = str(value)
    text = re.sub(r"\s+", " ", str(value).strip().casefold())
    compact = text.replace(" ", "")
    aliases = {
        "varchar": "string", "string": "string", "large_string": "string", "utf8": "string", "text": "string",
        "bool": "boolean", "boolean": "boolean", "tinyint": "int8", "smallint": "int16",
        "integer": "int32", "int": "int32", "bigint": "int64", "utinyint": "uint8",
        "usmallint": "uint16", "uinteger": "uint32", "ubigint": "uint64",
        "real": "float", "float": "float", "float32": "float", "double": "double",
        "float64": "double", "doubleprecision": "double", "date": "date", "date32[day]": "date",
        "date64[ms]": "date", "blob": "binary", "bytea": "binary", "binary": "binary",
        "varbinary": "binary", "null": "null", "timestamp": "timestamp",
        "timestampwithtimezone": "timestamp_tz", "timestamptz": "timestamp_tz",
    }
    if compact in aliases:
        return aliases[compact]
    if compact.startswith("timestamp["):
        return "timestamp_tz" if "tz=" in compact and "tz=none" not in compact else "timestamp"
    decimal = re.fullmatch(r"decimal(?:128|256)?\((\d+),(\d+)\)", compact)
    if decimal:
        return f"decimal({int(decimal[1])},{int(decimal[2])})"
    if compact.endswith("[]"):
        return f"array<{canonical_type(text[:-2])}>"
    if text.startswith("list<") or text.startswith("large_list<"):
        child = text[text.index("<") + 1:-1].strip()
        child = re.sub(r"^(?:item|element):\s*", "", child)
        return f"array<{canonical_type(child)}>"
    if text.startswith("map(") and text.endswith(")"):
        key, item = _parts(text[4:-1])
        return f"map<{canonical_type(key)},{canonical_type(item)}>"
    if text.startswith("map<") and text.endswith(">"):
        key, item = _parts(text[4:-1])
        key = re.sub(r"^key:\s*", "", key)
        item = re.sub(r"^value:\s*", "", item)
        return f"map<{canonical_type(key)},{canonical_type(item)}>"
    if (text.startswith("struct(") and text.endswith(")")) or (text.startswith("struct<") and text.endswith(">")):
        fields = _parts(text[7:-1])
        normalized = []
        for field in fields:
            name, separator, field_type = field.partition(":" if ":" in field else " ")
            if not separator:
                return compact
            normalized.append(f"{name.strip().strip(chr(34))}:{canonical_type(field_type)}")
        return "struct<" + ",".join(normalized) + ">"
    return compact
