"""Bounded evidence collection and confidence-calibrated semantic candidates."""

from __future__ import annotations

import itertools
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .errors import AnalysisError


MAX_GRAIN_FIELDS = 12
MAX_GRAIN_WIDTH = 3
MAX_GRAIN_CANDIDATES = 20
MAX_GRAIN_COMBINATIONS = 220
MAX_ENTITY_FIELDS = 20
MAX_FIELD_ROLES = 80
MAX_FUNCTIONAL_DEPENDENCIES = 40
MAX_METRIC_CANDIDATES = 10
MAX_QUESTIONS = 6

_DEPTHS = {"FAST", "STANDARD", "DEEP"}
_FOCUSES = {"general", "entity_count", "numeric", "grain"}
_KEY_WORDS = {"id", "key", "uuid", "identifier"}
_IDENTIFIER_WORDS = {"number", "num", "code", "reference", "ref"}
_ENTITY_WORDS = {
    "account", "asset", "application", "customer", "device", "employee", "entity",
    "machine", "member", "organization", "org", "person", "product", "project",
    "service", "tenant", "user", "vendor",
}
_EVENT_WORDS = {
    "action", "activity", "batch", "event", "execution", "ingestion", "ingest",
    "operation", "process", "processing", "request", "run", "session", "task",
    "trace", "transaction",
}
_TECHNICAL_WORDS = {
    "batch", "ingest", "ingestion", "load", "loaded", "process", "processing",
    "record", "row", "trace",
}
_DIMENSION_WORDS = {
    "campaign", "channel", "city", "class", "category", "country", "currency",
    "department", "domain", "group", "hostname", "kind", "language", "level",
    "owner", "path", "platform", "postal", "referrer", "region", "segment",
    "source", "status", "team", "tier", "type", "url", "zip", "zone",
}
_MEASURE_WORDS = {
    "amount", "average", "count", "duration", "latency", "mean", "metric", "percent",
    "percentage", "price", "quantity", "rate", "ratio", "score", "share", "sum",
    "total", "value", "volume",
}
_TIME_WORDS = {
    "asof", "date", "day", "effective", "event", "month", "observed", "period",
    "snapshot", "time", "timestamp", "valid", "week", "year",
}
_BUSINESS_TIME_WORDS = {"date", "day", "event", "month", "observed", "period", "snapshot", "time", "timestamp", "week", "year"}


def _encoded(value: Any) -> tuple[Any, ...]:
    if isinstance(value, datetime):
        return ("datetime", value.isoformat())
    if isinstance(value, date):
        return ("date", value.isoformat())
    if isinstance(value, Decimal):
        return ("number", value)
    if isinstance(value, int) and not isinstance(value, bool):
        return ("number", Decimal(value))
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, tuple):
        return ("tuple", tuple(_encoded(part) for part in value))
    if isinstance(value, list):
        return ("list", tuple(_encoded(part) for part in value))
    if value is None:
        return ("null",)
    return ("string", value) if isinstance(value, str) else (type(value).__name__, repr(value))


def _name_tokens(name: str) -> set[str]:
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return {token for token in re.split(r"[^a-z0-9]+", expanded.casefold()) if token}


def _confidence_rank(value: str) -> int:
    return {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "UNKNOWN": 3}.get(value, 4)


def _validate_metadata(raw: Any, columns: set[str]) -> dict[str, Any]:
    """Validate the optional explicit semantic contract; PK declarations remain keys only."""
    if raw is None:
        return {"schema_version": 1, "columns": {}, "entity_keys": [], "event_keys": [],
                "observation_grain": [], "unique_constraints": []}
    allowed = {"schema_version", "columns", "entity_keys", "event_keys", "observation_grain", "unique_constraints"}
    if not isinstance(raw, dict) or set(raw) - allowed or raw.get("schema_version") != 1:
        raise AnalysisError("INPUT_SCHEMA_INVALID", "Semantic metadata must be a schema_version 1 object with supported fields.")
    roles = {"entity", "entity_key", "event", "event_key", "dimension", "time", "measure", "identifier", "observation_key", "primary_key"}
    raw_columns = raw.get("columns", {})
    if not isinstance(raw_columns, dict) or set(raw_columns) - columns:
        raise AnalysisError("SEMANTIC_REFERENCE_INVALID", "Semantic metadata columns must reference fields in the named dataset.")
    normalized_columns = {}
    for name, value in raw_columns.items():
        if isinstance(value, str):
            item = {"role": value}
        elif isinstance(value, dict) and not set(value) - {"role", "confidence"}:
            item = value
        else:
            raise AnalysisError("INPUT_SCHEMA_INVALID", f"Semantic metadata for {name!r} has an invalid shape.")
        if item.get("role") not in roles or item.get("confidence", "HIGH") not in {"HIGH", "MEDIUM", "LOW"}:
            raise AnalysisError("INPUT_SCHEMA_INVALID", f"Semantic metadata for {name!r} has an unsupported role or confidence.")
        normalized_columns[name] = {"role": item["role"], "confidence": item.get("confidence", "HIGH")}

    def field_groups(key: str, *, allow_empty: bool = True) -> list[list[str]]:
        value = raw.get(key, [])
        if key == "observation_grain" and value and all(isinstance(field, str) for field in value):
            value = [value]
        if not isinstance(value, list) or (not allow_empty and not value):
            raise AnalysisError("INPUT_SCHEMA_INVALID", f"Semantic metadata {key} must be a list of field groups.")
        groups = []
        for group in value:
            if (not isinstance(group, list) or not 1 <= len(group) <= 3
                    or any(not isinstance(field, str) or field not in columns for field in group)
                    or len(group) != len(set(group))):
                raise AnalysisError("SEMANTIC_REFERENCE_INVALID", f"Semantic metadata {key} contains an invalid field group.")
            groups.append(sorted(group))
        if len({tuple(group) for group in groups}) != len(groups):
            raise AnalysisError("INPUT_SCHEMA_INVALID", f"Semantic metadata {key} contains duplicate field groups.")
        return groups

    return {"schema_version": 1, "columns": normalized_columns,
            "entity_keys": field_groups("entity_keys"), "event_keys": field_groups("event_keys"),
            "observation_grain": field_groups("observation_grain"),
            "unique_constraints": field_groups("unique_constraints")}


def _time_role(tokens: set[str]) -> tuple[str, bool, int]:
    if tokens & {"ingest", "ingested", "ingestion", "load", "loaded", "import", "imported"}:
        return "INGESTION_TIMESTAMP", False, 7
    if tokens & {"process", "processing", "processed"}:
        return "PROCESSING_TIMESTAMP", False, 6
    if "valid" in tokens and "from" in tokens:
        return "VALID_TIME_START", False, 5
    if "valid" in tokens and "to" in tokens:
        return "VALID_TIME_END", False, 5
    if tokens & {"event", "transaction", "request"}:
        return "EVENT_TIME", True, 1
    if tokens & {"observed", "snapshot", "asof", "effective"}:
        return "OBSERVATION_TIME", True, 2
    if tokens & {"period", "month", "week", "year", "day", "date"}:
        return "PERIOD", True, 3
    if tokens & {"time", "timestamp"}:
        return "TIME", True, 4
    return "TEMPORAL_DIMENSION", True, 5


def _combo_stats(fields: tuple[str, ...], encoded_columns: dict[str, tuple[Any, ...]],
                 present_columns: dict[str, tuple[bool, ...]], cache: dict[tuple[str, ...], dict[str, Any]]) -> dict[str, Any]:
    if fields in cache:
        return cache[fields]
    row_count = len(next(iter(encoded_columns.values()))) if encoded_columns else 0
    keys: set[tuple[Any, ...]] = set()
    complete_rows = 0
    counts: Counter[tuple[Any, ...]] = Counter()
    for index in range(row_count):
        if not all(present_columns[name][index] for name in fields):
            continue
        key = tuple(encoded_columns[name][index] for name in fields)
        complete_rows += 1
        keys.add(key)
        counts[key] += 1
    result = {"distinct_count": len(keys), "complete_rows": complete_rows, "counts": counts,
              "unique_for_rows": complete_rows == row_count and len(keys) == row_count,
              "repeat_ratio": sum(count > 1 for count in counts.values()) / len(counts) if counts else 0.0}
    cache[fields] = result
    return result


def _period_recurrence(field: str, time_fields: list[str], encoded_columns: dict[str, tuple[Any, ...]],
                       present_columns: dict[str, tuple[bool, ...]]) -> tuple[float, int]:
    if not time_fields or not encoded_columns:
        return 0.0, 0
    row_count = len(encoded_columns[field])
    periods_by_value: dict[Any, set[Any]] = defaultdict(set)
    for index in range(row_count):
        if not present_columns[field][index]:
            continue
        value = encoded_columns[field][index]
        for time_field in time_fields:
            if present_columns[time_field][index]:
                periods_by_value[value].add(encoded_columns[time_field][index])
    repeated = sum(len(periods) >= 2 for periods in periods_by_value.values())
    total = len(periods_by_value)
    return (repeated / total if total else 0.0), repeated


def _same_period_collision(primary: str, secondary: str, time_fields: list[str],
                           encoded_columns: dict[str, tuple[Any, ...]],
                           present_columns: dict[str, tuple[bool, ...]]) -> bool:
    if not time_fields:
        return False
    seen: dict[tuple[Any, ...], set[Any]] = defaultdict(set)
    for index in range(len(encoded_columns[primary])):
        if not present_columns[primary][index] or not present_columns[secondary][index]:
            continue
        period = next((encoded_columns[field][index] for field in time_fields if present_columns[field][index]), None)
        if period is None:
            continue
        key = (encoded_columns[primary][index], period)
        seen[key].add(encoded_columns[secondary][index])
        if len(seen[key]) > 1:
            return True
    return False


def _functional_dependencies(fields: list[str], rows_count: int,
                              encoded_columns: dict[str, tuple[Any, ...]],
                              present_columns: dict[str, tuple[bool, ...]], maximum: int) -> list[dict[str, Any]]:
    candidates = sorted(set(fields))[:maximum]
    dependencies = []
    minimum_support = min(rows_count, max(3, int(rows_count * 0.5)))
    for determinant in candidates:
        distinct = len({encoded_columns[determinant][i] for i in range(rows_count) if present_columns[determinant][i]})
        if distinct < 2 or distinct >= rows_count * 0.95:
            continue
        for dependent in candidates:
            if determinant == dependent:
                continue
            valid_rows = 0
            dependent_values: dict[Any, set[Any]] = defaultdict(set)
            for index in range(rows_count):
                if present_columns[determinant][index] and present_columns[dependent][index]:
                    valid_rows += 1
                    dependent_values[encoded_columns[determinant][index]].add(encoded_columns[dependent][index])
                    if len(dependent_values[encoded_columns[determinant][index]]) > 1:
                        break
            if valid_rows < minimum_support or not dependent_values or any(len(values) != 1 for values in dependent_values.values()):
                continue
            if len(dependent_values) < 2:
                continue
            dependencies.append({"determinant": [determinant], "dependent": dependent,
                                 "support_count": valid_rows,
                                 "coverage": f"{valid_rows / rows_count:.6f}" if rows_count else "0.000000",
                                 "confidence": "HIGH" if valid_rows == rows_count else "MEDIUM",
                                 "evidence": [f"{len(dependent_values)} observed determinant values each map to one dependent value"]})
            if len(dependencies) >= maximum * 2:
                break
        if len(dependencies) >= maximum * 2:
            break
    dependencies.sort(key=lambda item: (item["determinant"], item["dependent"]))
    return dependencies[:MAX_FUNCTIONAL_DEPENDENCIES]


def infer_semantic_context(
    rows: list[dict[str, Any]],
    columns: list[str],
    *,
    total_rows: int | None = None,
    complete: bool = True,
    depth: str = "STANDARD",
    focus: str = "general",
    semantic_metadata: Any = None,
) -> dict[str, Any]:
    """Infer explicit semantic candidates from bounded, cached value and schema evidence.

    FAST limits evidence to direct field/identifier checks and width-two grain candidates.
    STANDARD adds bounded functional dependencies and composite grain; DEEP widens those
    candidate sets without scanning arbitrary-width combinations. ``focus=numeric`` skips
    entity and composite discovery when the requested calculation does not need it.
    """
    if depth not in _DEPTHS or focus not in _FOCUSES:
        raise AnalysisError("CONTRACT_INVALID", "Semantic inference depth or focus is unsupported.")
    total = len(rows) if total_rows is None else total_rows
    ordered_columns = sorted(set(columns))
    if len(ordered_columns) != len(columns):
        raise AnalysisError("INPUT_SCHEMA_INVALID", "Semantic inference needs unique column names.")
    metadata = _validate_metadata(semantic_metadata, set(ordered_columns))
    metadata_fingerprint = hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    metadata_columns = metadata["columns"]
    metadata_entity_groups = {tuple(group) for group in metadata["entity_keys"]}
    metadata_event_groups = {tuple(group) for group in metadata["event_keys"]}
    metadata_grains = {tuple(group) for group in metadata["observation_grain"]}
    explicit_entity_fields = {name for name, item in metadata_columns.items() if item["role"] in {"entity", "entity_key"}}
    explicit_event_fields = ({name for name, item in metadata_columns.items() if item["role"] in {"event", "event_key"}}
                             | {name for group in metadata_event_groups for name in group})
    explicit_time_fields = {name for name, item in metadata_columns.items() if item["role"] == "time"}
    explicit_dimension_fields = {name for name, item in metadata_columns.items() if item["role"] == "dimension"}
    explicit_measure_fields = {name for name, item in metadata_columns.items() if item["role"] == "measure"}
    explicit_identifier_fields = {name for name, item in metadata_columns.items() if item["role"] in {"identifier", "primary_key"}}
    explicit_observation_keys = {name for name, item in metadata_columns.items() if item["role"] == "observation_key"}

    encoded_columns: dict[str, tuple[Any, ...]] = {}
    present_columns: dict[str, tuple[bool, ...]] = {}
    field_facts: dict[str, dict[str, Any]] = {}
    temporal_fields: list[str] = []
    dimension_fields: list[str] = []
    measure_fields: list[str] = []

    for name in ordered_columns:
        values = tuple(row.get(name) for row in rows)
        encoded = tuple(_encoded(value) for value in values)
        present_mask = tuple(value is not None for value in values)
        present = [value for value in values if value is not None]
        distinct = len({encoded[index] for index, is_present in enumerate(present_mask) if is_present})
        present_count = len(present)
        ratio = distinct / present_count if present_count else 0.0
        tokens = _name_tokens(name)
        key_like = bool(tokens & _KEY_WORDS)
        identifier_like = bool(tokens & _IDENTIFIER_WORDS)
        entity_like = bool(tokens & _ENTITY_WORDS)
        event_like = bool(tokens & _EVENT_WORDS)
        technical_like = bool(tokens & _TECHNICAL_WORDS)
        dimension_like = bool(tokens & _DIMENSION_WORDS)
        measure_like = bool(tokens & _MEASURE_WORDS)
        temporal_count = sum(isinstance(value, (date, datetime)) for value in present)
        numeric_count = sum(isinstance(value, (int, Decimal)) and not isinstance(value, bool) for value in present)
        boolean_values = bool(present) and all(isinstance(value, bool) for value in present)
        explicit = metadata_columns.get(name, {})
        explicit_role = explicit.get("role")
        is_temporal = bool(present and temporal_count == present_count) or name in explicit_time_fields
        if explicit_role == "time":
            is_temporal = True
        if is_temporal:
            role = "TIME_DIMENSION"
            temporal_fields.append(name)
        elif explicit_role in {"entity", "entity_key"} or name in explicit_entity_fields:
            role = "ENTITY_KEY_CANDIDATE"
        elif explicit_role in {"event", "event_key"} or name in explicit_event_fields:
            role = "EVENT_KEY_CANDIDATE"
        elif explicit_role in {"identifier", "primary_key", "observation_key"} or name in explicit_identifier_fields | explicit_observation_keys:
            role = "CANDIDATE_KEY"
        elif explicit_role == "dimension" or name in explicit_dimension_fields:
            role = "DIMENSION_CANDIDATE"
            dimension_fields.append(name)
        elif explicit_role == "measure" or name in explicit_measure_fields:
            role = "MEASURE_CANDIDATE"
            measure_fields.append(name)
        elif present and numeric_count == present_count and not key_like and not identifier_like:
            role = "DIMENSION_CANDIDATE" if dimension_like or (distinct <= 3 and not measure_like) else "MEASURE_CANDIDATE"
            (dimension_fields if role == "DIMENSION_CANDIDATE" else measure_fields).append(name)
        elif present:
            role = "DIMENSION_CANDIDATE"
            dimension_fields.append(name)
        else:
            role = "UNKNOWN"
        encoded_columns[name] = encoded
        present_columns[name] = present_mask
        field_facts[name] = {
            "values": values, "present_count": present_count, "null_count": len(values) - present_count,
            "distinct_count": distinct, "uniqueness_ratio": ratio, "tokens": tokens,
            "key_like": key_like, "identifier_like": identifier_like, "entity_like": entity_like,
            "event_like": event_like, "technical_like": technical_like, "dimension_like": dimension_like,
            "measure_like": measure_like, "role": role, "explicit_role": explicit_role,
            "explicit_confidence": explicit.get("confidence", "HIGH"), "temporal": is_temporal,
            "numeric": bool(present and numeric_count == present_count), "boolean": boolean_values,
        }

    business_time_fields: list[str] = []
    time_role_by_field: dict[str, tuple[str, bool, int]] = {}
    for name in temporal_fields:
        tokens = field_facts[name]["tokens"]
        time_role = _time_role(tokens)
        if name in explicit_time_fields or field_facts[name]["explicit_role"] == "time":
            time_role = ("BUSINESS_TIME", True, 0)
        time_role_by_field[name] = time_role
        if time_role[1]:
            business_time_fields.append(name)
    business_time_fields.sort(key=lambda name: (time_role_by_field[name][2], name))
    temporal_fields.sort(key=lambda name: (time_role_by_field[name][2], name))

    repetitions: dict[str, tuple[float, int]] = {
        name: _period_recurrence(name, business_time_fields[:4], encoded_columns, present_columns)
        for name in ordered_columns if not field_facts[name]["temporal"]
    }
    row_repetitions = {}
    for name in ordered_columns:
        fact = field_facts[name]
        values = [encoded_columns[name][index] for index, present in enumerate(present_columns[name]) if present]
        counts = Counter(values)
        row_repetitions[name] = sum(count > 1 for count in counts.values()) / len(counts) if counts else 0.0

    cache: dict[tuple[str, ...], dict[str, Any]] = {}
    unique_fields = [name for name in ordered_columns if rows and field_facts[name]["null_count"] == 0
                     and field_facts[name]["distinct_count"] == len(rows)]
    unique_record_keys = []
    event_key_candidates = []
    technical_key_fields = set()
    for name in unique_fields:
        fact = field_facts[name]
        tokens = fact["tokens"]
        event_key = fact["key_like"] and bool(tokens & {"event", "transaction", "request", "execution", "run", "trace", "session"})
        technical = fact["technical_like"]
        if technical:
            technical_key_fields.add(name)
        key_kind = "EVENT_KEY" if event_key else "TECHNICAL_KEY" if technical else "UNCLASSIFIED_KEY"
        unique_record_keys.append({"field": name, "cardinality": fact["distinct_count"], "confidence": "HIGH",
                                  "key_kind": key_kind,
                                  "evidence": ["every profiled row has a non-null distinct value"],
                                  "semantic_role": key_kind})
        if event_key or name in explicit_event_fields:
            event_key_candidates.append({"field": name, "fields": [name], "cardinality": fact["distinct_count"],
                                         "confidence": "HIGH" if complete else "LOW", "key_kind": "EVENT_KEY",
                                         "evidence": ["identifier is unique and its generic field tokens indicate an event occurrence"]})
    unique_record_keys.sort(key=lambda item: item["field"])
    event_key_candidates.sort(key=lambda item: item["field"])

    event_descriptors = [name for name in ordered_columns if field_facts[name]["tokens"] &
                         {"action", "activity", "event", "kind", "operation", "transaction", "type"}
                         and not field_facts[name]["key_like"] and field_facts[name]["distinct_count"] >= 2]
    for fields in sorted(metadata_event_groups):
        stats = _combo_stats(fields, encoded_columns, present_columns, cache)
        event_key_candidates.append({"field": fields[0] if len(fields) == 1 else " × ".join(fields),
                                     "fields": list(fields), "cardinality": stats["distinct_count"],
                                     "confidence": "HIGH" if stats["unique_for_rows"] and complete else "LOW",
                                     "key_kind": "EVENT_KEY",
                                     "evidence": ["authoritative metadata declares an event key"] +
                                                (["observed data does not satisfy the declared key"] if not stats["unique_for_rows"] else [])})
    event_key_candidates = sorted({tuple(item["fields"]): item for item in event_key_candidates}.values(),
                                  key=lambda item: item["fields"])
    event_stream = bool(event_key_candidates and event_descriptors)
    if metadata_event_groups or explicit_event_fields:
        event_stream = True
    if event_stream:
        for item in event_key_candidates:
            item["confidence"] = "HIGH" if complete and event_descriptors else "MEDIUM"
            item["evidence"].append("event-specific descriptive fields support an event-stream interpretation")

    entities: list[dict[str, Any]] = []
    entity_single_fields: set[str] = set()
    ambiguous_roles: list[dict[str, Any]] = []
    if focus != "numeric":
        for name in ordered_columns:
            fact = field_facts[name]
            distinct = fact["distinct_count"]
            ratio = fact["uniqueness_ratio"]
            repeat_time, repeated_period_values = repetitions.get(name, (0.0, 0))
            repeated_rows = row_repetitions.get(name, 0.0)
            tokens = fact["tokens"]
            explicit_entity = name in explicit_entity_fields
            event_key = name in {item["field"] for item in event_key_candidates} or name in explicit_event_fields
            if fact["temporal"] or distinct < 2 or not fact["present_count"] or event_key or name in technical_key_fields:
                continue
            if fact["role"] == "MEASURE_CANDIDATE" and not (fact["key_like"] or fact["identifier_like"] or name in explicit_entity_fields):
                continue
            if fact["event_like"] and not explicit_entity:
                continue
            if fact["dimension_like"] and not explicit_entity:
                continue
            if event_stream and ratio >= 0.95 and not explicit_entity:
                continue
            has_identifier = fact["key_like"] or fact["identifier_like"]
            has_entity_name = fact["entity_like"] or "entity" in tokens
            collides_with_axis = (not event_stream and has_entity_name and has_identifier
                                  and any(field_facts[other]["dimension_like"]
                                          and _same_period_collision(name, other, business_time_fields[:2],
                                                                     encoded_columns, present_columns)
                                          for other in dimension_fields if other != name))
            high_cardinality_recurrence = (repeat_time >= 0.5 and distinct >= 4 and ratio >= 0.15 and ratio < 0.95
                                           and not fact["dimension_like"] and not fact["event_like"]
                                           and not fact["numeric"] and not fact["boolean"])
            snapshot_identity = (not business_time_fields and has_entity_name and has_identifier
                                 and ratio >= 0.95 and not fact["event_like"])
            named_identity = ((has_identifier and (has_entity_name or repeat_time >= 0.25 or repeated_rows >= 0.5))
                              or ("entity" in tokens and (repeat_time >= 0.25 or repeated_rows >= 0.5)))
            structural_identity = high_cardinality_recurrence
            if collides_with_axis and not explicit_entity:
                continue
            if not (explicit_entity or named_identity or snapshot_identity or structural_identity):
                if (business_time_fields and ratio >= 0.10 and repeat_time >= 0.5 and not fact["dimension_like"]
                        and not fact["event_like"] and not fact["key_like"]):
                    ambiguous_roles.append({"fields": [name], "candidate_roles": ["ENTITY_KEY_CANDIDATE", "DIMENSION_CANDIDATE"],
                                           "confidence": "UNKNOWN",
                                           "supporting_evidence": [f"{distinct} values recur across observed periods"],
                                           "contradicting_evidence": ["identifier or entity semantics are not established"]})
                continue
            supporting = [f"{distinct} distinct non-null values across {fact['present_count']} profiled observations"]
            contradicting = []
            if has_identifier:
                supporting.append("field has a generic identifier-shaped name")
            if has_entity_name:
                supporting.append("field name contains a generic persistent-entity cue")
            if collides_with_axis:
                contradicting.append("identifier values collide across a descriptive axis within the same business period")
            if repeated_period_values:
                supporting.append(f"{repeated_period_values} values recur across at least two business-time values")
            elif repeated_rows:
                supporting.append("values repeat across multiple observations")
            if fact["null_count"]:
                contradicting.append(f"{fact['null_count']} profiled observations have no key value")
            if event_key or fact["technical_like"]:
                contradicting.append("field tokens indicate an event or technical identifier")
            if distinct <= 3 and not has_identifier and not explicit_entity:
                contradicting.append("very small categorical population has no independent entity-key evidence")
            if explicit_entity:
                confidence = fact["explicit_confidence"]
                supporting.append("authoritative metadata declares an entity or entity key")
            elif snapshot_identity:
                confidence = "MEDIUM" if complete and len(rows) >= 3 and not fact["null_count"] else "LOW"
                supporting.append("single-snapshot structure and an entity-key name support a row-per-entity interpretation")
            elif has_identifier and has_entity_name and repeat_time >= 0.5 and complete and len(rows) >= 30 and not contradicting:
                confidence = "HIGH"
            elif has_identifier and (has_entity_name or repeat_time >= 0.25):
                confidence = "MEDIUM" if complete and not fact["null_count"] else "LOW"
            elif structural_identity:
                confidence = "MEDIUM" if complete and len(rows) >= 30 else "LOW"
            else:
                confidence = "LOW"
            if fact["null_count"] and confidence == "HIGH":
                confidence = "MEDIUM"
            entities.append({"fields": [name], "role": "PERSISTENT_ENTITY_KEY_CANDIDATE",
                             "key_kind": "ENTITY_KEY", "cardinality": distinct,
                             "uniqueness_ratio": f"{ratio:.6f}",
                             "temporal_repetition_ratio": f"{repeat_time:.6f}" if business_time_fields else None,
                             "confidence": confidence, "supporting_evidence": supporting,
                             "contradicting_evidence": contradicting,
                             "evidence": supporting + (["negative evidence lowers confidence"] if contradicting else [])})
            entity_single_fields.add(name)

        # Infer a composite entity key only when a named identifier component collides
        # within the same business period and a stable categorical component resolves it.
        if depth != "FAST" and len(rows) and business_time_fields:
            component_fields = [name for name in ordered_columns if field_facts[name]["entity_like"]
                                and (field_facts[name]["identifier_like"] or field_facts[name]["key_like"])
                                and name not in entity_single_fields
                                and not field_facts[name]["event_like"] and not field_facts[name]["technical_like"]]
            partners = [name for name in dimension_fields if field_facts[name]["dimension_like"]
                        and field_facts[name]["distinct_count"] >= 2]
            composite_count = 0
            for primary in component_fields:
                for secondary in partners:
                    if primary == secondary or not _same_period_collision(primary, secondary, business_time_fields[:2],
                                                                          encoded_columns, present_columns):
                        continue
                    fields = tuple(sorted((primary, secondary)))
                    stats = _combo_stats(fields, encoded_columns, present_columns, cache)
                    if stats["distinct_count"] < 2 or stats["distinct_count"] >= len(rows):
                        continue
                    recurring = 0
                    group_periods: dict[Any, set[Any]] = defaultdict(set)
                    for index in range(len(rows)):
                        if not all(present_columns[name][index] for name in fields):
                            continue
                        key = tuple(encoded_columns[name][index] for name in fields)
                        period = next((encoded_columns[field][index] for field in business_time_fields
                                       if present_columns[field][index]), None)
                        if period is not None:
                            group_periods[key].add(period)
                    recurring = sum(len(periods) >= 2 for periods in group_periods.values())
                    recurrence = recurring / len(group_periods) if group_periods else 0.0
                    if recurrence < 0.5:
                        continue
                    supporting = [f"{stats['distinct_count']} composite values recur across business periods",
                                  f"{primary} collides within a period and {secondary} resolves the observed identity ambiguity"]
                    confidence = "MEDIUM" if complete and len(rows) >= 8 else "LOW"
                    entities.append({"fields": list(fields), "role": "PERSISTENT_ENTITY_KEY_CANDIDATE",
                                     "key_kind": "COMPOSITE_ENTITY_KEY", "cardinality": stats["distinct_count"],
                                     "uniqueness_ratio": f"{stats['distinct_count'] / max(len(rows), 1):.6f}",
                                     "temporal_repetition_ratio": f"{recurrence:.6f}", "confidence": confidence,
                                     "supporting_evidence": supporting, "contradicting_evidence": [],
                                     "evidence": supporting})
                    composite_count += 1
                    if composite_count >= 12:
                        break
                if composite_count >= 12:
                    break

    # Authoritative composite metadata can identify an entity key even when one part
    # is a low-cardinality dimension; database primary/unique constraints alone cannot.
    existing_entity_groups = {tuple(item["fields"]) for item in entities}
    for fields in sorted(metadata_entity_groups):
        if fields in existing_entity_groups:
            continue
        stats = _combo_stats(fields, encoded_columns, present_columns, cache)
        entities.append({"fields": list(fields), "role": "PERSISTENT_ENTITY_KEY_CANDIDATE",
                         "key_kind": "ENTITY_KEY" if len(fields) == 1 else "COMPOSITE_ENTITY_KEY",
                         "cardinality": stats["distinct_count"],
                         "uniqueness_ratio": f"{stats['distinct_count'] / max(len(rows), 1):.6f}",
                         "temporal_repetition_ratio": None, "confidence": "HIGH" if complete else "MEDIUM",
                         "supporting_evidence": ["authoritative metadata explicitly declares the entity key"],
                         "contradicting_evidence": [], "evidence": ["authoritative metadata explicitly declares the entity key"]})
    entities.sort(key=lambda item: (_confidence_rank(item["confidence"]), -len(item["fields"]), item["fields"]))
    entities = entities[:MAX_ENTITY_FIELDS]
    entity_names = {name for entity in entities for name in entity["fields"]}

    functional_dependencies: list[dict[str, Any]] = []
    if focus != "numeric" and depth in {"STANDARD", "DEEP"}:
        fd_fields = sorted(set(entity_names) | set(dimension_fields) | set(business_time_fields))
        functional_dependencies = _functional_dependencies(fd_fields, len(rows), encoded_columns,
                                                            present_columns, 12 if depth == "STANDARD" else 16)

    # Dimensions are the descriptive axes left after explicit entity/event/key and
    # time roles. A repeated low-cardinality value is not promoted to an entity.
    event_key_fields = {name for item in event_key_candidates for name in item["fields"]}
    identifier_fields = set(unique_fields) | explicit_identifier_fields | explicit_observation_keys
    dimensions = sorted(name for name in dimension_fields
                        if name not in entity_names and name not in event_key_fields
                        and name not in identifier_fields and not field_facts[name]["temporal"])
    measures = sorted(name for name in measure_fields if name not in entity_names)

    # Search only plausible semantic dimensions. The field cap and width cap bound the
    # worst case to 220 combinations; encoded values and combo statistics are reused.
    grain_candidates: list[dict[str, Any]] = []
    if focus != "numeric" and rows:
        declared_grains = sorted(metadata_grains)
        for fields in declared_grains:
            stats = _combo_stats(fields, encoded_columns, present_columns, cache)
            conflict = not stats["unique_for_rows"]
            grain_candidates.append({"fields": list(fields), "observation_count": len(rows),
                                     "distinct_key_count": stats["distinct_count"],
                                     "uniqueness_ratio": f"{stats['distinct_count'] / max(len(rows), 1):.6f}",
                                     "confidence": "LOW" if conflict or not complete else "HIGH",
                                     "metadata_declared": True,
                                     "evidence": ["authoritative metadata declares the observation grain"] +
                                                (["observed nulls or duplicate keys contradict the declaration"] if conflict else [])})

        event_grains = [tuple(item["fields"]) for item in event_key_candidates] if event_stream else []
        if event_grains:
            for fields in event_grains:
                stats = _combo_stats(fields, encoded_columns, present_columns, cache)
                if stats["unique_for_rows"]:
                    grain_candidates.append({"fields": list(fields), "observation_count": len(rows),
                                             "distinct_key_count": stats["distinct_count"],
                                             "uniqueness_ratio": "1.000000",
                                             "confidence": "MEDIUM" if complete and len(rows) >= 10 else "LOW",
                                             "metadata_declared": False,
                                             "evidence": ["unique event key identifies each observed event", "event-specific descriptors support event-stream grain"]})
        else:
            selected_entities = [tuple(entity["fields"]) for entity in entities]
            grain_fields = set(business_time_fields[:4]) | set(dimensions[:8]) | set(explicit_observation_keys)
            for fields in selected_entities:
                grain_fields.update(fields)
            for fields in metadata_event_groups:
                grain_fields.update(fields)
            # A uniquely identifying entity key is a valid snapshot grain.
            grain_fields.update(name for name in entity_names if name in unique_fields)
            role_order = {name: 0 for name in entity_names}
            role_order.update({name: 1 for name in business_time_fields})
            role_order.update({name: 2 for name in dimensions})
            role_order.update({name: 0 for name in explicit_observation_keys})
            maximum_fields = 6 if depth == "FAST" else 10 if depth == "STANDARD" else MAX_GRAIN_FIELDS
            ordered_grain_fields = sorted(grain_fields, key=lambda name: (role_order.get(name, 3), name))[:maximum_fields]
            maximum_width = 2 if depth == "FAST" else MAX_GRAIN_WIDTH
            examined = 0
            for width in range(1, min(maximum_width, len(ordered_grain_fields)) + 1):
                width_candidates = []
                for fields in itertools.combinations(ordered_grain_fields, width):
                    examined += 1
                    if examined > MAX_GRAIN_COMBINATIONS:
                        break
                    if any(field_facts[name]["null_count"] for name in fields):
                        continue
                    stats = _combo_stats(fields, encoded_columns, present_columns, cache)
                    if not stats["unique_for_rows"]:
                        continue
                    includes_entity = set(fields) & entity_names
                    includes_time = set(fields) & set(business_time_fields)
                    includes_dimension = set(fields) & set(dimensions)
                    if not (includes_entity or includes_time or includes_dimension or set(fields) & explicit_observation_keys):
                        continue
                    evidence = ["non-null field combination uniquely identifies every profiled observation"]
                    if includes_entity:
                        evidence.append("combination includes a persistent-entity key candidate")
                    if includes_time:
                        evidence.append("combination includes business observation/event time")
                    if includes_dimension:
                        evidence.append("combination includes a descriptive axis needed to distinguish observed rows")
                    confidence = "MEDIUM" if complete and len(rows) >= 10 else "LOW"
                    width_candidates.append({"fields": list(fields), "observation_count": len(rows),
                                             "distinct_key_count": stats["distinct_count"],
                                             "uniqueness_ratio": "1.000000", "confidence": confidence,
                                             "metadata_declared": False, "evidence": evidence})
                if width_candidates:
                    grain_candidates.extend(width_candidates[:MAX_GRAIN_CANDIDATES])
                    break
                if examined > MAX_GRAIN_COMBINATIONS:
                    break

        unique_grains: dict[tuple[str, ...], dict[str, Any]] = {}
        for item in grain_candidates:
            key = tuple(item["fields"])
            previous = unique_grains.get(key)
            if previous is None or _confidence_rank(item["confidence"]) < _confidence_rank(previous["confidence"]):
                unique_grains[key] = item
        grain_candidates = sorted(unique_grains.values(),
                                  key=lambda item: (len(item["fields"]), _confidence_rank(item["confidence"]), item["fields"]))[:MAX_GRAIN_CANDIDATES]

    selected = next((item for item in grain_candidates if item.get("metadata_declared")), None)
    if selected is None and grain_candidates:
        selected = grain_candidates[0]
    grain = {"fields": selected["fields"] if selected else [],
             "confidence": selected["confidence"] if selected else "UNKNOWN",
             "evidence": selected["evidence"] if selected else ["Available evidence does not establish a bounded unique observation grain."],
             "interpretation": "candidate observation key; business meaning remains subject to source semantics"}

    relationships = []
    simple_entities = [item for item in entities if len(item["fields"]) == 1]
    if len(simple_entities) >= 2:
        for left, right in itertools.combinations(simple_entities, 2):
            fields = sorted((left["fields"][0], right["fields"][0]))
            stats = _combo_stats(tuple(fields), encoded_columns, present_columns, cache)
            if stats["distinct_count"] > 1:
                relationships.append({"entity_fields": fields, "cardinality": stats["distinct_count"],
                                      "confidence": "MEDIUM" if complete else "LOW",
                                      "evidence": ["both key candidates co-occur in the same observations"]})
            if len(relationships) >= 10:
                break

    dataset_shape = ("event_stream" if event_stream else
                     "longitudinal" if entities and business_time_fields else
                     "snapshot" if entities else
                     "time_series" if business_time_fields and not dimensions else
                     "aggregated" if business_time_fields and dimensions and measures else
                     "cross_sectional" if dimensions and measures else "ambiguous")

    duplicate_rows = len(rows) - len({_encoded(tuple(row.get(name) for name in ordered_columns)) for row in rows})
    quality_risks = []
    if not complete:
        quality_risks.append({"code": "SAMPLED_PROFILE", "confidence": "HIGH",
                              "description": "Value evidence and inferred roles describe only the profiled prefix."})
    if duplicate_rows:
        quality_risks.append({"code": "DUPLICATE_OBSERVATIONS", "confidence": "HIGH",
                              "description": f"{duplicate_rows} exact duplicate row(s) were observed; intended duplicate semantics are unknown."})
    for entity in entities:
        missing = sum(field_facts[name]["null_count"] for name in entity["fields"])
        if missing:
            quality_risks.append({"code": "ENTITY_KEY_MISSING", "fields": entity["fields"], "confidence": "MEDIUM",
                                  "description": "A candidate entity key has missing values; population coverage may be incomplete."})
    if event_key_candidates and not event_stream:
        quality_risks.append({"code": "EVENT_VS_ROW_KEY_AMBIGUITY", "confidence": "LOW",
                              "description": "An event-shaped unique key is present, but other event evidence is insufficient to decide whether it is an event or technical row key."})
    if focus == "numeric":
        quality_risks.append({"code": "SEMANTIC_DISCOVERY_DEFERRED", "confidence": "HIGH",
                              "description": "Entity and composite-grain discovery was skipped for the numeric-only FAST profile focus."})

    candidate_metrics = [{"id": "observation-count", "kind": "observation_count", "operation": "count",
                          "confidence": "HIGH", "rationale": "Exact number of rows in the named input." if complete else "Exact total rows; semantic values are a profiled prefix."}]
    for entity in entities[:3]:
        fields = entity["fields"]
        field_label = "-".join(re.sub(r"[^A-Za-z0-9_.:-]+", "-", field)[:20] for field in fields)
        candidate_metrics.append({"id": "distinct-" + field_label[:48], "kind": "entity_count_candidate",
                                  "operation": "distinct_count", "columns": fields,
                                  "cardinality": entity["cardinality"], "confidence": entity["confidence"],
                                  "rationale": "Distinct candidate entity-key count; verify that the named key has the intended business meaning."})
    if temporal_fields and dimensions and len(candidate_metrics) < MAX_METRIC_CANDIDATES:
        dimension = dimensions[0]
        candidate_metrics.append({"id": "composition-" + re.sub(r"[^A-Za-z0-9_.:-]+", "-", dimension)[:48],
                                  "kind": "category_composition_candidate", "operation": "composition",
                                  "group_by": [dimension], "period_column": business_time_fields[0] if business_time_fields else temporal_fields[0],
                                  "confidence": "MEDIUM" if complete else "LOW",
                                  "rationale": "Observed category shares can be compared across periods; this remains descriptive evidence."})
    for name in measures[:max(0, MAX_METRIC_CANDIDATES - len(candidate_metrics))]:
        candidate_metrics.append({"id": "distribution-" + re.sub(r"[^A-Za-z0-9_.:-]+", "-", name)[:48],
                                  "kind": "numeric_distribution_candidate", "operation": "distribution", "column": name,
                                  "confidence": "LOW" if not complete else "MEDIUM",
                                  "rationale": "Numeric values support a deterministic distribution summary; units and business meaning are unknown."})
    candidate_metrics = candidate_metrics[:MAX_METRIC_CANDIDATES]

    questions = []
    if temporal_fields and measures:
        questions.append(f"How do candidate measures change across {business_time_fields[0] if business_time_fields else temporal_fields[0]}?")
    if temporal_fields and entities:
        questions.append(f"Does the represented entity population change across {business_time_fields[0] if business_time_fields else temporal_fields[0]}?")
    if temporal_fields and entities and measures:
        questions.extend(["How do aggregate changes compare with the retained-entity cohort?",
                          "Are changes broad-based or concentrated among a small subset?"])
    if temporal_fields and dimensions:
        questions.append(f"Did the category mix shift across {business_time_fields[0] if business_time_fields else temporal_fields[0]}?")
    if measures:
        questions.append("Do distribution summaries reveal movement hidden by an average?")
    if temporal_fields and not grain_candidates and focus != "numeric":
        questions.append("Does the available key evidence establish a stable observation grain?")

    temporal_summary = []
    for name in temporal_fields[:20]:
        values = [value for value in field_facts[name]["values"] if value is not None]
        ordered = sorted(value.isoformat() if isinstance(value, (date, datetime)) else str(value) for value in values)
        temporal_summary.append({"field": name, "distinct_count": field_facts[name]["distinct_count"],
                                 "minimum": ordered[0] if ordered else None, "maximum": ordered[-1] if ordered else None,
                                 "temporal_role": time_role_by_field[name][0], "business_time": time_role_by_field[name][1],
                                 "confidence": "HIGH" if complete and values else "LOW"})

    identifier_shaped_fields = {name for name in ordered_columns
                                if field_facts[name]["key_like"] or field_facts[name]["identifier_like"]}
    for name in ordered_columns:
        fact = field_facts[name]
        if name in entity_names:
            fact["role"] = "ENTITY_KEY_CANDIDATE"
        elif name in event_key_fields:
            fact["role"] = "EVENT_KEY_CANDIDATE"
        elif name in technical_key_fields:
            fact["role"] = "TECHNICAL_KEY_CANDIDATE"
        elif name in identifier_fields | identifier_shaped_fields and fact["role"] not in {"TIME_DIMENSION", "MEASURE_CANDIDATE"}:
            fact["role"] = "CANDIDATE_KEY"
        elif name in dimensions:
            fact["role"] = "DIMENSION_CANDIDATE"
        elif name in measures:
            fact["role"] = "MEASURE_CANDIDATE"

    role_priority = {"ENTITY_KEY_CANDIDATE": 0, "EVENT_KEY_CANDIDATE": 1, "CANDIDATE_KEY": 2,
                     "TIME_DIMENSION": 3, "DIMENSION_CANDIDATE": 4, "MEASURE_CANDIDATE": 5,
                     "TECHNICAL_KEY_CANDIDATE": 6, "UNKNOWN": 7}
    entity_confidence_by_field: dict[str, str] = {}
    for entity in entities:
        for name in entity["fields"]:
            previous = entity_confidence_by_field.get(name)
            if previous is None or _confidence_rank(entity["confidence"]) < _confidence_rank(previous):
                entity_confidence_by_field[name] = entity["confidence"]
    field_roles = []
    for name in sorted(ordered_columns, key=lambda item: (role_priority.get(field_facts[item]["role"], 8), item))[:MAX_FIELD_ROLES]:
        fact = field_facts[name]
        supporting = []
        contradicting = []
        if fact["key_like"] or fact["identifier_like"]:
            supporting.append("name has a generic identifier-shaped token")
        if fact["distinct_count"]:
            supporting.append(f"{fact['distinct_count']} distinct values across {fact['present_count']} non-null observations")
        if fact["null_count"]:
            contradicting.append(f"{fact['null_count']} values are missing")
        if fact["event_like"] and fact["role"] != "EVENT_KEY_CANDIDATE":
            contradicting.append("event-shaped naming does not by itself establish a persistent entity")
        if fact["technical_like"]:
            contradicting.append("technical lifecycle tokens indicate a machine-generated identifier or timestamp")
        if fact["dimension_like"] and fact["role"] != "ENTITY_KEY_CANDIDATE":
            supporting.append("name is a generic descriptive-axis cue")
        field_roles.append({"field": name, "role": fact["role"],
                            "confidence": entity_confidence_by_field.get(name, "HIGH" if name in explicit_event_fields else
                                         "MEDIUM" if fact["role"] != "UNKNOWN" and complete else "LOW"),
                            "distinct_count": fact["distinct_count"], "non_null_count": fact["present_count"],
                            "uniqueness_ratio": f"{fact['uniqueness_ratio']:.6f}",
                            "supporting_evidence": supporting, "contradicting_evidence": contradicting})

    candidate_key_groups = []
    for item in unique_record_keys:
        candidate_key_groups.append({"fields": [item["field"]], "kind": item["key_kind"],
                                     "confidence": "HIGH", "evidence": item["evidence"]})
    unique_key_names = {item["field"] for item in unique_record_keys}
    for name in sorted(identifier_shaped_fields - unique_key_names):
        candidate_key_groups.append({"fields": [name], "kind": "NON_UNIQUE_IDENTIFIER_CANDIDATE",
                                     "confidence": "LOW",
                                     "evidence": ["identifier-shaped field contains repeated or missing values",
                                                  "uniqueness alone and identifier naming do not establish entity semantics"]})
    for fields in sorted(metadata["unique_constraints"]):
        stats = _combo_stats(tuple(fields), encoded_columns, present_columns, cache)
        candidate_key_groups.append({"fields": fields, "kind": "DECLARED_UNIQUE_CONSTRAINT",
                                     "confidence": "HIGH" if stats["unique_for_rows"] else "LOW",
                                     "evidence": ["source metadata declares a unique constraint"] +
                                                (["observed values violate the declared constraint"] if not stats["unique_for_rows"] else [])})
    for item in entities:
        if len(item["fields"]) > 1:
            candidate_key_groups.append({"fields": item["fields"], "kind": "COMPOSITE_ENTITY_KEY",
                                         "confidence": item["confidence"], "evidence": item["evidence"]})

    if not complete:
        limitations = ["Candidate counts, recurrence and grain describe only the profiled prefix; they are not population-wide entity estimates."]
    else:
        limitations = []
    if ambiguous_roles:
        limitations.append("Some repeated fields have both entity-key and dimension interpretations; no definitive role was assigned.")
    if not semantic_metadata:
        limitations.append("No authoritative field-role or source constraint metadata was supplied; names and observed values remain evidence, not truth.")
    if len(ordered_columns) > MAX_FIELD_ROLES:
        limitations.append(f"Field-role evidence was capped at {MAX_FIELD_ROLES} columns for bounded output.")
    return {
        "schema_version": 2,
        "analysis_depth": depth,
        "focus": focus,
        "metadata_evidence": {"provided": semantic_metadata is not None,
                               "fingerprint_sha256": metadata_fingerprint,
                               "explicit_role_count": len(metadata_columns),
                               "entity_key_group_count": len(metadata_entity_groups),
                               "event_key_group_count": len(metadata_event_groups),
                               "unique_constraint_count": len(metadata["unique_constraints"]),
                               "observation_grain_declared": bool(metadata_grains)},
        "observations": {"count": total, "profiled_count": len(rows), "complete": complete,
                         "unit": "rows", "confidence": "HIGH" if complete else "LOW"},
        "dataset_shape": dataset_shape,
        "grain": grain,
        "grain_candidates": grain_candidates,
        "entities": entities,
        "entity_key_candidates": [item for item in entities],
        "event_key_candidates": event_key_candidates[:10],
        "unique_record_key_candidates": unique_record_keys[:10],
        "candidate_key_groups": candidate_key_groups[:30],
        "relationships": relationships,
        "functional_dependencies": functional_dependencies,
        "ambiguous_roles": ambiguous_roles[:20],
        "field_roles": field_roles,
        "temporal_dimensions": temporal_summary,
        "dimensions": dimensions[:40],
        "measures": measures[:40],
        "candidate_metrics": candidate_metrics,
        "analytical_questions": questions[:MAX_QUESTIONS],
        "quality_risks": quality_risks[:20],
        "limitations": limitations[:20],
    }


def validate_semantic_context(raw: Any, *, known_columns: set[str] | None = None) -> dict[str, Any]:
    """Validate v1/v2 semantic context while retaining v1 profile compatibility."""
    if not isinstance(raw, dict) or raw.get("schema_version") not in {1, 2}:
        raise AnalysisError("CONTRACT_INVALID", "Semantic context must use schema_version 1 or 2.")
    observations, grain = raw.get("observations"), raw.get("grain")
    if not isinstance(observations, dict) or observations.get("unit") != "rows":
        raise AnalysisError("CONTRACT_INVALID", "Semantic context observations must distinguish row count.")
    if not isinstance(observations.get("count"), int) or isinstance(observations.get("count"), bool) or observations["count"] < 0:
        raise AnalysisError("CONTRACT_INVALID", "Semantic context observation count is invalid.")
    if (not isinstance(observations.get("profiled_count"), int) or isinstance(observations.get("profiled_count"), bool)
            or not 0 <= observations["profiled_count"] <= observations["count"]):
        raise AnalysisError("CONTRACT_INVALID", "Semantic context profiled row count is invalid.")
    if observations.get("confidence") not in {"HIGH", "MEDIUM", "LOW", "UNKNOWN"} or not isinstance(observations.get("complete"), bool):
        raise AnalysisError("CONTRACT_INVALID", "Semantic context observation confidence/completeness is invalid.")
    if not isinstance(grain, dict) or grain.get("confidence") not in {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}:
        raise AnalysisError("CONTRACT_INVALID", "Semantic context grain confidence is invalid.")
    if not isinstance(grain.get("fields"), list) or any(not isinstance(name, str) for name in grain["fields"]):
        raise AnalysisError("CONTRACT_INVALID", "Semantic context grain fields are invalid.")

    def check_fields(names: Any, label: str, *, nonempty: bool = False, unique: bool = False) -> None:
        if (not isinstance(names, list) or (nonempty and not names)
                or any(not isinstance(name, str) or not name for name in names)
                or (unique and len(names) != len(set(names)))):
            raise AnalysisError("CONTRACT_INVALID", f"Semantic context {label} fields are invalid.")
        if known_columns is not None and set(names) - known_columns:
            raise AnalysisError("SEMANTIC_REFERENCE_INVALID", f"Semantic context {label} references unknown columns.")

    check_fields(grain["fields"], "grain", unique=True)
    list_limits = {"grain_candidates": MAX_GRAIN_CANDIDATES, "entities": MAX_ENTITY_FIELDS,
                   "entity_key_candidates": MAX_ENTITY_FIELDS, "unique_record_key_candidates": 10,
                   "event_key_candidates": 10, "candidate_key_groups": 30, "relationships": 10,
                   "functional_dependencies": MAX_FUNCTIONAL_DEPENDENCIES, "ambiguous_roles": 20,
                   "field_roles": MAX_FIELD_ROLES, "temporal_dimensions": 20, "dimensions": 40,
                   "measures": 40, "candidate_metrics": MAX_METRIC_CANDIDATES,
                   "analytical_questions": MAX_QUESTIONS, "quality_risks": 20, "limitations": 20}
    for field, maximum in list_limits.items():
        items = raw.get(field, [])
        if not isinstance(items, list) or len(items) > maximum:
            raise AnalysisError("ANALYSIS_BUDGET_EXCEEDED", f"Semantic context {field} exceeds its bounded list limit.")
    for list_name in ("entities", "entity_key_candidates"):
        for index, entity in enumerate(raw.get(list_name, [])):
            if not isinstance(entity, dict):
                raise AnalysisError("CONTRACT_INVALID", f"Semantic entity candidate {index} is invalid.")
            check_fields(entity.get("fields"), f"{list_name}[{index}]", nonempty=True, unique=True)
            if entity.get("confidence") not in {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}:
                raise AnalysisError("CONTRACT_INVALID", f"Semantic entity candidate {index} has invalid confidence.")
            for evidence_field in ("evidence", "supporting_evidence", "contradicting_evidence"):
                if evidence_field in entity and (not isinstance(entity[evidence_field], list)
                        or len(entity[evidence_field]) > 20
                        or any(not isinstance(item, str) or not item.strip() or len(item) > 500 for item in entity[evidence_field])):
                    raise AnalysisError("CONTRACT_INVALID", f"Semantic entity candidate {index} has invalid evidence.")
    for index, candidate in enumerate(raw.get("grain_candidates", [])):
        if not isinstance(candidate, dict) or candidate.get("confidence") not in {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}:
            raise AnalysisError("CONTRACT_INVALID", f"Semantic grain candidate {index} is invalid.")
        check_fields(candidate.get("fields"), f"grain_candidates[{index}]", nonempty=True, unique=True)
    for list_name, key in (("unique_record_key_candidates", "field"), ("event_key_candidates", "field")):
        for index, item in enumerate(raw.get(list_name, [])):
            if not isinstance(item, dict) or not isinstance(item.get(key), str):
                raise AnalysisError("CONTRACT_INVALID", f"Semantic {list_name} entry {index} is invalid.")
            if list_name == "event_key_candidates" and "fields" in item:
                check_fields(item["fields"], f"{list_name}[{index}]", nonempty=True, unique=True)
                if known_columns is not None and set(item["fields"]) - known_columns:
                    raise AnalysisError("SEMANTIC_REFERENCE_INVALID", f"Semantic {list_name}[{index}] references unknown columns.")
            else:
                check_fields([item[key]], f"{list_name}[{index}]")
    for index, item in enumerate(raw.get("field_roles", [])):
        if not isinstance(item, dict) or item.get("role") not in {
            "ENTITY_KEY_CANDIDATE", "EVENT_KEY_CANDIDATE", "CANDIDATE_KEY", "TECHNICAL_KEY_CANDIDATE",
            "TIME_DIMENSION", "DIMENSION_CANDIDATE", "MEASURE_CANDIDATE", "UNKNOWN",
        } or item.get("confidence") not in {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}:
            raise AnalysisError("CONTRACT_INVALID", f"Semantic field role {index} is invalid.")
        check_fields([item.get("field")], f"field_roles[{index}]")
        for field in ("supporting_evidence", "contradicting_evidence"):
            evidence = item.get(field, [])
            if not isinstance(evidence, list) or len(evidence) > 20 or any(not isinstance(value, str) or len(value) > 500 for value in evidence):
                raise AnalysisError("CONTRACT_INVALID", f"Semantic field role {index} evidence is invalid.")
    for index, collection in enumerate(("candidate_key_groups", "relationships", "ambiguous_roles")):
        for item_index, item in enumerate(raw.get(collection, [])):
            if not isinstance(item, dict):
                raise AnalysisError("CONTRACT_INVALID", f"Semantic {collection} entry {item_index} is invalid.")
            names = item.get("fields", item.get("entity_fields"))
            check_fields(names, f"{collection}[{item_index}]", nonempty=True, unique=True)
            if "confidence" in item and item["confidence"] not in {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}:
                raise AnalysisError("CONTRACT_INVALID", f"Semantic {collection} entry {item_index} has invalid confidence.")
    if raw.get("schema_version") == 2:
        metadata_evidence = raw.get("metadata_evidence")
        if (not isinstance(metadata_evidence, dict)
                or not isinstance(metadata_evidence.get("provided"), bool)
                or not isinstance(metadata_evidence.get("fingerprint_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", metadata_evidence["fingerprint_sha256"])):
            raise AnalysisError("CONTRACT_INVALID", "Semantic context metadata provenance is invalid.")
    for field in ("dimensions", "measures"):
        check_fields(raw.get(field, []), field, unique=True)
    for field in ("analytical_questions", "limitations"):
        items = raw.get(field, [])
        if any(not isinstance(value, str) or not value.strip() or len(value) > 1000 for value in items):
            raise AnalysisError("CONTRACT_INVALID", f"Semantic context {field} must contain bounded text.")
    if raw.get("schema_version") == 2:
        if raw.get("analysis_depth") not in _DEPTHS or raw.get("focus") not in _FOCUSES:
            raise AnalysisError("CONTRACT_INVALID", "Semantic context v2 needs a supported depth and focus.")
        if raw.get("dataset_shape") not in {"event_stream", "longitudinal", "snapshot", "time_series", "aggregated", "cross_sectional", "ambiguous"}:
            raise AnalysisError("CONTRACT_INVALID", "Semantic context v2 dataset_shape is invalid.")
        for index, dependency in enumerate(raw.get("functional_dependencies", [])):
            if not isinstance(dependency, dict) or not isinstance(dependency.get("determinant"), list) or not isinstance(dependency.get("dependent"), str):
                raise AnalysisError("CONTRACT_INVALID", f"Semantic functional dependency {index} is invalid.")
            check_fields(dependency["determinant"] + [dependency["dependent"]], f"functional_dependencies[{index}]", unique=True)
    return raw
