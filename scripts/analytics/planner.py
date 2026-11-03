"""Conservative SQL and minimum-sufficient materialization planning."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from .errors import ReadOnlyError, ValidationError

WRITE_WORDS = {"insert", "update", "delete", "merge", "create", "alter", "drop",
               "truncate", "grant", "revoke", "copy", "load", "export", "import",
               "optimize", "vacuum", "refresh", "call", "execute", "exec", "restore",
               "repair", "replace", "rename", "comment", "msck", "reset", "set", "use",
               "cache", "uncache", "begin", "commit", "rollback", "transaction"}
UNSUPPORTED_LOCAL_WORDS = {"join", "union", "intersect", "except", "group", "having",
                           "order", "window", "qualify", "offset", "lateral", "pivot", "unpivot"}


@dataclass(frozen=True)
class SQLToken:
    kind: str
    value: str
    start: int
    end: int
    depth: int


@dataclass(frozen=True)
class QueryRequirements:
    """The local data a read-only query needs, independent of its SQL output shape."""

    tables: tuple[str, ...]
    required_columns: tuple[str, ...]
    row_predicate: str = ""
    aggregates: tuple[str, ...] = ()
    grouping: tuple[str, ...] = ()
    ordering: tuple[str, ...] = ()
    distinct: bool = False
    limit: int | None = None
    requires_all_columns: bool = False
    requires_full_row_population: bool = True
    local_engine_compatible: bool = True
    unsupported_reason: str = ""


@dataclass(frozen=True)
class QueryPlan:
    sql: str
    source_name: str
    projection: tuple[str, ...]
    predicate: str = ""
    limit: int | None = None
    requirements: QueryRequirements | None = None
    source_span: tuple[int, int] = (0, 0)
    alias: str = ""

    @property
    def fingerprint(self) -> str:
        normalized = re.sub(r"\s+", " ", self.sql.strip()).rstrip(";")
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AcquisitionPlan:
    operation_id: str
    workspace_identity: str
    source_name: str
    source_version: str
    projection: tuple[str, ...]
    predicate: str
    max_rows: int
    max_bytes: int
    estimated_bytes: int | None
    force_refresh: bool
    intent_projection: tuple[str, ...] | None = None
    source_schema_identity: str = ""
    selected_schema_identity: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def statement(self) -> str:
        fields = "*" if self.projection == ("*",) else ", ".join(quote_identifier(c) for c in self.projection)
        source = ".".join(quote_identifier(part) for part in self.source_name.split("."))
        sql = f"SELECT {fields} FROM {source}"
        if self.predicate:
            sql += " WHERE " + self.predicate
        sql += f" LIMIT {self.max_rows}"
        return sql


def tokenize(sql: str) -> list[SQLToken]:
    tokens: list[SQLToken] = []
    index = 0
    depth = 0
    while index < len(sql):
        char = sql[index]
        if char.isspace():
            index += 1
            continue
        if sql.startswith("--", index) or sql.startswith("/*", index) or sql.startswith("*/", index):
            raise ReadOnlyError("SQL comments are not accepted by the Analytics query router")
        start = index
        if char in {"'", "`", '"'}:
            quote_char = char
            kind = "literal" if char == "'" else "identifier"
            index += 1
            value: list[str] = []
            while index < len(sql):
                if sql[index] == quote_char:
                    if index + 1 < len(sql) and sql[index + 1] == quote_char:
                        value.append(quote_char)
                        index += 2
                        continue
                    index += 1
                    break
                value.append(sql[index])
                index += 1
            else:
                raise ValidationError("SQL contains an unterminated quoted value")
            tokens.append(SQLToken(kind, "".join(value), start, index, depth))
            continue
        word = re.match(r"[A-Za-z_$][A-Za-z0-9_$]*", sql[index:])
        if word:
            index += len(word.group(0))
            tokens.append(SQLToken("word", word.group(0).casefold(), start, index, depth))
            continue
        number = re.match(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", sql[index:])
        if number:
            index += len(number.group(0))
            tokens.append(SQLToken("number", number.group(0), start, index, depth))
            continue
        operator = next((candidate for candidate in ("<=", ">=", "<>", "!=", "||", "::")
                         if sql.startswith(candidate, index)), None)
        if operator:
            index += len(operator)
            tokens.append(SQLToken("symbol", operator, start, index, depth))
            continue
        if char == ";":
            tokens.append(SQLToken("symbol", char, start, index + 1, depth))
            index += 1
            continue
        if char == "(":
            tokens.append(SQLToken("symbol", char, start, index + 1, depth))
            depth += 1
            index += 1
            continue
        if char == ")":
            depth -= 1
            if depth < 0:
                raise ValidationError("SQL parentheses are unbalanced")
            tokens.append(SQLToken("symbol", char, start, index + 1, depth))
            index += 1
            continue
        if char in {".", ",", "*", "+", "-", "/", "%", "=", "<", ">", "!", ":"}:
            tokens.append(SQLToken("symbol", char, start, index + 1, depth))
            index += 1
            continue
        raise ValidationError("SQL contains an unsupported character")
    if depth != 0:
        raise ValidationError("SQL parentheses are unbalanced")
    return tokens


def ensure_read_only(sql: str) -> str:
    if not isinstance(sql, str) or not sql.strip() or len(sql.encode("utf-8")) > 1_000_000:
        raise ValidationError("SQL is empty or exceeds Anvil's 1 MB query limit")
    tokens = tokenize(sql)
    semicolons = [i for i, token in enumerate(tokens)
                  if token.kind == "symbol" and token.value == ";"]
    if semicolons:
        if len(semicolons) != 1 or semicolons[0] != len(tokens) - 1:
            raise ReadOnlyError("Only one SQL statement can be executed at a time")
    words = [token.value for token in tokens if token.kind == "word"]
    if not words or words[0] not in {"select", "with", "values", "show", "describe", "explain"}:
        raise ReadOnlyError("Analytics accepts read-only SQL statements only")
    if any(word in WRITE_WORDS for word in words):
        raise ReadOnlyError("Analytics accepts read-only SQL statements only")
    return sql.strip().rstrip(";").strip()


def parse_local_query(sql: str) -> QueryPlan | None:
    """Extract conservative local data requirements from a single-table SELECT."""
    normalized = ensure_read_only(sql)
    tokens = tokenize(normalized)
    if not tokens or tokens[0].value != "select":
        return None
    from_index = next((i for i, token in enumerate(tokens)
                       if token.depth == 0 and token.kind == "word" and token.value == "from"), None)
    if from_index is None:
        return None
    select_start = tokens[0].end
    from_start = tokens[from_index].start
    projection_tokens = tokens[1:from_index]

    cursor = from_index + 1
    name_parts: list[str] = []
    while cursor < len(tokens) and len(name_parts) < 3:
        token = tokens[cursor]
        if token.kind not in {"word", "identifier"}:
            return None
        name_parts.append(token.value if token.kind == "identifier" else _original_word(normalized, token))
        cursor += 1
        if len(name_parts) < 3:
            if cursor >= len(tokens) or tokens[cursor].value != ".":
                return None
            cursor += 1
    if len(name_parts) != 3:
        return None
    if cursor < len(tokens) and tokens[cursor].depth == 0 and tokens[cursor].value == ".":
        return None
    source_name = ".".join(name_parts)
    source_start = tokens[from_index + 1].start
    source_end = tokens[cursor - 1].end

    # Preserve a source alias because DuckDB resolves qualified columns against
    # it after the source relation is replaced with the immutable local view.
    alias = ""
    if cursor < len(tokens) and tokens[cursor].depth == 0:
        if tokens[cursor].kind == "word" and tokens[cursor].value == "as":
            if cursor + 1 >= len(tokens) or tokens[cursor + 1].kind not in {"word", "identifier"}:
                return None
            alias = tokens[cursor + 1].value
            cursor += 2
        elif (tokens[cursor].kind in {"word", "identifier"} and
              tokens[cursor].value not in {"where", "group", "having", "order", "limit"}):
            alias = tokens[cursor].value
            cursor += 1

    where_token = next((token for token in tokens[cursor:]
                        if token.depth == 0 and token.kind == "word" and token.value == "where"), None)
    limit_token = next((token for token in tokens[cursor:]
                        if token.depth == 0 and token.kind == "word" and token.value == "limit"), None)
    for token in tokens[cursor:]:
        if token.depth == 0 and token.kind == "word" and token.value in {
                "join", "union", "intersect", "except", "window", "qualify",
                "offset", "lateral", "pivot", "unpivot"}:
            return None
    if where_token and limit_token and where_token.start > limit_token.start:
        return None
    if sum(token.depth == 0 and token.kind == "word" and token.value == "where"
           for token in tokens[cursor:]) > 1:
        return None
    if sum(token.depth == 0 and token.kind == "word" and token.value == "limit"
           for token in tokens[cursor:]) > 1:
        return None

    predicate = ""
    if where_token:
        clause_end = next((token.start for token in tokens[cursor:]
                           if token.depth == 0 and token.kind == "word" and
                           token.value in {"group", "having", "order", "limit"} and
                           token.start > where_token.start), len(normalized))
        end = clause_end
        predicate = normalized[where_token.end:end].strip()
        if not _safe_predicate(predicate):
            return None

    limit: int | None = None
    if limit_token:
        after = [token for token in tokens if token.start >= limit_token.end]
        if not after or after[0].kind != "number" or not re.fullmatch(r"\d+", after[0].value):
            return None
        limit = int(after[0].value)
        remaining = after[1:]
        if remaining and not (len(remaining) == 1 and remaining[0].value == ";"):
            return None
    if any(token.depth == 0 and token.kind == "word" and token.value in
           {"join", "union", "intersect", "except"} for token in tokens):
        return None

    requirements = _query_requirements(normalized, tokens, source_name, alias,
                                       predicate, limit, projection_tokens)
    if requirements is None:
        return None
    # Projection remains a backwards-compatible summary for existing callers;
    # coverage decisions consume QueryRequirements directly.
    projection = ("*",) if requirements.requires_all_columns else requirements.required_columns
    return QueryPlan(normalized, source_name, projection, predicate, limit,
                     requirements, (source_start, source_end), alias)


def _query_requirements(sql: str, tokens: list[SQLToken], source_name: str,
                        alias: str, predicate: str, limit: int | None,
                        projection_tokens: list[SQLToken]) -> QueryRequirements | None:
    """Collect column references without treating aggregate output names as source columns."""
    words = [token.value for token in tokens if token.kind == "word"]
    aggregates = tuple(dict.fromkeys(token.value.upper() for index, token in enumerate(tokens[:-1])
                                    if token.kind == "word" and token.value in
                                    {"count", "min", "max", "sum", "avg"} and
                                    tokens[index + 1].value == "("))
    select_star = any(token.value == "*" and token.depth == 0 for token in projection_tokens)

    reserved = {
        "select", "distinct", "all", "from", "where", "and", "or", "not", "is", "null",
        "like", "in", "between", "true", "false", "date", "timestamp", "as", "group", "by",
        "having", "order", "asc", "desc", "nulls", "first", "last", "limit", "case", "when",
        "then", "else", "end", "cast", "interval", "current_date", "current_timestamp",
        "count", "min", "max", "sum", "avg", "coalesce", "nullif", "abs", "round",
        "lower", "upper", "trim", "length", "substring", "extract", "year", "month", "day",
    }
    table_parts = {part.casefold() for part in source_name.split(".")}
    aliases = {alias.casefold()} if alias else set()
    required: list[str] = []
    for index, token in enumerate(tokens):
        if token.kind not in {"word", "identifier"}:
            continue
        value = token.value
        folded = value.casefold()
        if token.kind == "word" and folded in reserved:
            continue
        if folded in table_parts or folded in aliases:
            continue
        # Function names, table names and qualified-name prefixes are not columns.
        previous = tokens[index - 1] if index else None
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        if following and following.value == "(" and token.kind == "word":
            continue
        if following and following.value == ".":
            continue
        if previous and previous.kind == "word" and previous.value == "as":
            continue
        if previous and previous.value == ".":
            pass
        if not any(existing.casefold() == value.casefold() for existing in required):
            required.append(value)

    if select_star:
        required_columns: tuple[str, ...] = ()
    else:
        required_columns = tuple(required)
    group_by: tuple[str, ...] = ()
    order_by: tuple[str, ...] = ()
    for clause, output in (("group", "group"), ("order", "order")):
        clause_index = next((i for i, token in enumerate(tokens)
                             if token.depth == 0 and token.kind == "word" and token.value == clause), None)
        if clause_index is None or clause_index + 1 >= len(tokens) or tokens[clause_index + 1].value != "by":
            continue
        end = next((token.start for token in tokens[clause_index + 2:]
                    if token.depth == 0 and token.kind == "word" and
                    token.value in ({"having", "order", "limit"} if output == "group" else {"limit"})),
                   len(sql))
        clause_text = sql[tokens[clause_index + 1].end:end].strip()
        columns = tuple(dict.fromkeys(token.value for token in tokenize(clause_text)
                                      if token.kind in {"word", "identifier"} and
                                      token.value not in reserved and
                                      token.value.casefold() not in table_parts | aliases))
        if output == "group":
            group_by = columns
        else:
            order_by = columns

    return QueryRequirements(
        tables=(source_name,), required_columns=required_columns,
        row_predicate=predicate, aggregates=aggregates, grouping=group_by,
        ordering=order_by, distinct=any(token.depth == 0 and token.kind == "word" and
                                        token.value == "distinct" for token in projection_tokens),
        limit=limit, requires_all_columns=select_star,
        requires_full_row_population=True)


def _original_word(sql: str, token: SQLToken) -> str:
    return sql[token.start:token.end]


def _projection(tokens: list[SQLToken], source: str) -> tuple[str, ...] | None:
    groups: list[list[SQLToken]] = [[]]
    for token in tokens:
        if token.value == "," and token.depth == 0:
            groups.append([])
        else:
            groups[-1].append(token)
    result: list[str] = []
    for group in groups:
        if len(group) == 1 and group[0].value == "*":
            if len(groups) != 1:
                return None
            return ("*",)
        if len(group) != 1 or group[0].kind not in {"word", "identifier"}:
            return None
        result.append(group[0].value if group[0].kind == "identifier"
                      else _original_word(source, group[0]))
    return tuple(result) if result else None


def _safe_predicate(value: str) -> bool:
    if not value:
        return False
    try:
        tokens = tokenize(value)
    except ValidationError:
        return False
    allowed_words = {"and", "or", "not", "is", "null", "like", "in", "between",
                     "true", "false", "date", "timestamp"}
    allowed_symbols = {",", "*", "+", "-", "/", "%", "=", "<", ">", "!",
                       "<=", ">=", "<>", "!=", "(", ")"}
    for index, token in enumerate(tokens):
        if token.kind == "word":
            if token.value not in allowed_words:
                # A bare name is a column, but a function call is outside the
                # exact local-coverage subset.
                if index + 1 < len(tokens) and tokens[index + 1].value == "(":
                    return False
        elif token.kind == "symbol" and token.value not in allowed_symbols:
            return False
    return True


def quote_identifier(value: str) -> str:
    if not value or any(ord(char) < 32 for char in value):
        raise ValidationError("SQL identifier is empty or contains control characters")
    return "`" + value.replace("`", "``") + "`"


def rewrite_expression_identifiers(value: str, quote: str = '"') -> str:
    """Translate quoted identifiers while preserving string literal contents."""
    tokens = tokenize(value)
    pieces: list[str] = []
    cursor = 0
    for token in tokens:
        pieces.append(value[cursor:token.start])
        if token.kind == "identifier":
            pieces.append(quote + token.value.replace(quote, quote + quote) + quote)
        else:
            pieces.append(value[token.start:token.end])
        cursor = token.end
    pieces.append(value[cursor:])
    return "".join(pieces)


def plan_materialization(*, workspace_identity: str, source_name: str,
                         projection: list[str] | tuple[str, ...], predicate: str = "",
                         source_version: str = "", max_rows: int = 100_000,
                         max_bytes: int = 512 * 1024 * 1024,
                         estimated_bytes: int | None = None,
                         full_table_confirmed: bool = False,
                         force_refresh: bool = False,
                         source_schema_identity: str = "") -> AcquisitionPlan:
    source_parts = source_name.split(".")
    if len(source_parts) != 3 or any(not part or any(ord(char) < 32 or char in "/\\" for char in part)
                                     for part in source_parts):
        raise ValidationError("Materialization source must be one fully qualified table")
    columns = tuple(projection)
    intent_projection = columns
    if not columns:
        raise ValidationError("Materialization requires at least one projected column")
    if columns != ("*",) and (len(columns) > 1000 or len({c.casefold() for c in columns}) != len(columns)):
        raise ValidationError("Materialization projection must contain at most 1000 unique columns")
    if columns != ("*",) and any(not column or any(ord(char) < 32 or char in "/\\;" for char in column)
                                  for column in columns):
        raise ValidationError("Materialization columns must be simple catalog column names")
    if not 1 <= max_rows <= 1_000_000:
        raise ValidationError("Materialization row bound must be between 1 and 1000000")
    if not 1_048_576 <= max_bytes <= 1_073_741_824:
        raise ValidationError("Materialization byte bound must be between 1 MiB and 1 GiB")
    if estimated_bytes is not None and estimated_bytes < 0:
        raise ValidationError("Estimated source size must not be negative")
    if estimated_bytes is not None and estimated_bytes > max_bytes:
        raise ValidationError("Estimated materialization size exceeds the configured byte limit")
    source_version = source_version.strip()[:200] or "UNVERIFIED"
    probe_projection = "*" if columns == ("*",) else ", ".join(quote_identifier(c) for c in columns)
    probe_source = ".".join(quote_identifier(part) for part in source_parts)
    probe = f"SELECT {probe_projection} FROM {probe_source}" + (f" WHERE {predicate}" if predicate.strip() else "")
    parsed = parse_local_query(probe)
    if parsed is None or parsed.source_name != source_name:
        raise ValidationError("Materialization projection or filter is outside the supported safe subset")
    if columns != ("*",) and parsed.predicate:
        # The local snapshot must include filter inputs even when they are not
        # part of the user's visible SELECT projection.
        required = predicate_columns(parsed.predicate)
        present = {column.casefold() for column in columns}
        columns = (*columns, *(column for column in required if column.casefold() not in present))
        if len(columns) > 1000:
            raise ValidationError("Materialization requires more than 1000 projected and filter columns")
    identity = {"workspace": workspace_identity, "source": source_name,
                "source_version": source_version, "projection": columns,
                "source_schema_identity": source_schema_identity,
                "predicate": re.sub(r"\s+", " ", parsed.predicate).strip(),
                "max_rows": max_rows, "max_bytes": max_bytes}
    if force_refresh:
        identity["refresh"] = str(uuid.uuid4())
    operation_id = hashlib.sha256(json.dumps(identity, sort_keys=True,
                                               separators=(",", ":")).encode()).hexdigest()
    return AcquisitionPlan(operation_id, workspace_identity, source_name, source_version,
                           columns, parsed.predicate, max_rows, max_bytes,
                           estimated_bytes, force_refresh, intent_projection,
                           source_schema_identity)


def predicate_columns(predicate: str) -> tuple[str, ...]:
    keywords = {"and", "or", "not", "is", "null", "like", "in", "between", "true", "false"}
    found: list[str] = []
    seen: set[str] = set()
    tokens = tokenize(predicate)
    for index, token in enumerate(tokens):
        if token.kind == "identifier":
            name = token.value
        elif token.kind == "word" and token.value not in keywords:
            if token.value in {"date", "timestamp"} and index + 1 < len(tokens) and tokens[index + 1].kind == "literal":
                continue
            name = token.value
        else:
            continue
        if name.casefold() not in seen:
            found.append(name)
            seen.add(name.casefold())
    return tuple(found)
