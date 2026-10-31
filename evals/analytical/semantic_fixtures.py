"""Public, generic semantic-certification inputs; expected answers live in ground_truth/."""

from __future__ import annotations

from typing import Any


SEMANTIC_FIXTURE_VERSION = "semantic-foundation-v1"


def _case(identifier: str, columns: list[str], rows: list[dict[str, Any]],
          metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    value = {"id": identifier, "columns": columns, "rows": rows}
    if metadata is not None:
        value["semantic_metadata"] = metadata
    return value


def build_semantic_cases() -> list[dict[str, Any]]:
    """Create small independent semantic cases without embedding their hidden answers."""
    cases = []

    cases.append(_case("A-repeated-entity", ["entity_id", "period", "metric"], [
        {"entity_id": f"E{entity:02d}", "period": f"2025-{period:02d}", "metric": entity * 10 + period}
        for entity in range(1, 6) for period in range(1, 5)]))

    cases.append(_case("B-event-identifier", ["user_id", "event_id", "timestamp", "event_type", "value"], [
        {"user_id": f"U{user:02d}", "event_id": f"EV{user:02d}-{event:02d}",
         "timestamp": f"2025-01-{event:02d}T10:00:00", "event_type": "read" if event % 2 else "write",
         "value": event + user}
        for user in range(1, 5) for event in range(1, 5)]))

    cases.append(_case("C-composite-observation-grain", ["customer_id", "period", "product", "amount"], [
        {"customer_id": f"C{customer:02d}", "period": f"2025-{period:02d}",
         "product": product, "amount": customer * 100 + period * 10 + index}
        for customer in range(1, 5) for period in range(1, 4)
        for index, product in enumerate(("alpha", "beta"))]))

    cases.append(_case("D-composite-entity-key", ["account_number", "country", "period", "balance"], [
        {"account_number": f"A{account:02d}", "country": country,
         "period": f"2025-{period:02d}", "balance": account * 100 + period}
        for account in range(1, 5) for country in ("north", "south") for period in range(1, 4)]))

    cases.append(_case("E-technical-row-id", ["row_uuid", "customer_id", "period", "metric"], [
        {"row_uuid": f"R-{entity:02d}-{period:02d}", "customer_id": f"C{entity:02d}",
         "period": f"2025-{period:02d}", "metric": entity + period}
        for entity in range(1, 6) for period in range(1, 4)]))

    cases.append(_case("F-snapshot", ["customer_id", "region", "tier", "balance"], [
        {"customer_id": f"C{customer:02d}", "region": ("east", "west", "north")[customer % 3],
         "tier": ("basic", "plus")[customer % 2], "balance": customer * 100}
        for customer in range(1, 7)]))

    cases.append(_case("G-event-stream", ["user_id", "event_id", "event_time", "event_type", "amount"], [
        {"user_id": f"U{user:02d}", "event_id": f"X{user:02d}-{event:02d}",
         "event_time": f"2025-02-{event:02d}T09:30:00", "event_type": ("view", "save", "share")[event % 3],
         "amount": event + user}
        for user in range(1, 6) for event in range(1, 5)]))

    cases.append(_case("H-aggregated", ["region", "month", "total_sales", "order_count"], [
        {"region": region, "month": f"2025-{month:02d}",
         "total_sales": (index + 1) * month * 100, "order_count": (index + 2) * month}
        for index, region in enumerate(("east", "west", "north", "south")) for month in range(1, 4)]))

    cases.append(_case("I-pure-time-series", ["timestamp", "cpu_usage", "memory_usage"], [
        {"timestamp": f"2025-03-{day:02d}T12:00:00", "cpu_usage": day * 2,
         "memory_usage": day * 3}
        for day in range(1, 13)]))

    cases.append(_case("J-multiple-entities", ["customer_id", "product_id", "date", "quantity"], [
        {"customer_id": f"C{customer:02d}", "product_id": f"P{product:02d}",
         "date": f"2025-{period:02d}-01", "quantity": customer + product + period}
        for customer in range(1, 5) for product in range(1, 4) for period in range(1, 3)]))

    cases.append(_case("K-dimensional-categories", ["customer_id", "region", "status", "segment", "period", "metric"], [
        {"customer_id": f"C{customer:02d}", "region": ("east", "west")[customer % 2],
         "status": ("open", "closed")[period % 2], "segment": ("small", "large")[customer % 2],
         "period": f"2025-{period:02d}", "metric": customer * period}
        for customer in range(1, 6) for period in range(1, 4)]))

    cases.append(_case("L-numeric-identifier", ["device_id", "period", "reading"], [
        {"device_id": device, "period": f"2025-{period:02d}", "reading": device * period}
        for device in (101, 202, 303) for period in range(1, 5)]))

    cases.append(_case("M-string-measure", ["month", "monthly_amount", "category"], [
        {"month": f"2025-{period:02d}", "monthly_amount": str(amount), "category": category}
        for period, amount, category in ((1, "10.5", "a"), (2, "12.0", "b"), (3, "13.5", "a"), (4, "11.0", "b"))]))

    cases.append(_case("N-nullable-identifier", ["customer_id", "period", "metric"], [
        {"customer_id": None if customer == 4 and period == 3 else f"C{customer:02d}",
         "period": f"2025-{period:02d}", "metric": customer * 10 + period}
        for customer in range(1, 5) for period in range(1, 4)]))

    duplicate_base = [{"entity_id": f"E{entity}", "period": f"2025-{period:02d}", "metric": entity * 10 + period}
                     for entity in range(1, 4) for period in range(1, 3)]
    cases.append(_case("O-duplicated-observations", ["entity_id", "period", "metric"],
                       duplicate_base + [dict(row) for row in duplicate_base]))

    cases.append(_case("P-nonunique-request-key", ["request_id", "period", "latency"], [
        {"request_id": f"Q{index % 2}", "period": f"2025-{index // 4 + 1:02d}", "latency": index + 1}
        for index in range(8)]))

    cases.append(_case("Q-multiple-time-fields", ["customer_id", "event_time", "ingested_at", "processed_at", "metric"], [
        {"customer_id": f"C{customer:02d}", "event_time": f"2025-04-{period:02d}T08:00:00",
         "ingested_at": f"2025-04-{period:02d}T08:05:{customer:02d}",
         "processed_at": f"2025-04-{period:02d}T08:10:{customer:02d}", "metric": customer + period}
        for customer in range(1, 5) for period in range(1, 4)]))

    cases.append(_case("R-stable-functional-dependency", ["customer_id", "region", "period", "metric"], [
        {"customer_id": f"C{customer:02d}", "region": ("east", "west", "north")[customer % 3],
         "period": f"2025-{period:02d}", "metric": customer * period}
        for customer in range(1, 7) for period in range(1, 4)]))

    cases.append(_case("S-changing-dimension", ["customer_id", "region", "period", "metric"], [
        {"customer_id": f"C{customer:02d}", "region": ("east", "west", "north")[(customer + period) % 3],
         "period": f"2025-{period:02d}", "metric": customer * period}
        for customer in range(1, 7) for period in range(1, 4)]))

    cases.append(_case("T-high-cardinality-category", ["referrer", "period", "visits"], [
        {"referrer": f"source-{source:02d}", "period": f"2025-{period:02d}", "visits": source + period}
        for source in range(1, 21) for period in range(1, 4)]))

    cases.append(_case("U-low-cardinality-entity", ["device_id", "period", "measurement"], [
        {"device_id": f"D{device}", "period": f"2025-{period:02d}", "measurement": device + period}
        for device in range(1, 4) for period in range(1, 4)]))

    cases.append(_case("V-no-semantic-signal", ["a", "b", "c", "d"], [
        {"a": ("x", "y")[index % 2], "b": ("m", "n")[index // 2 % 2],
         "c": ("p", "q")[index % 2], "d": ("u", "v")[index // 2 % 2]}
        for index in range(8)]))

    metadata = {"schema_version": 1, "columns": {"a": "entity_key", "t": "time", "x": "measure"},
                "entity_keys": [["a"]], "observation_grain": ["a", "t"]}
    cases.append(_case("W-authoritative-metadata", ["a", "t", "x"], [
        {"a": f"K{entity}", "t": f"2025-{period:02d}", "x": entity * period}
        for entity in range(1, 4) for period in range(1, 4)], metadata))

    cases.append(_case("X-misleading-name", ["customer_id", "event_id", "user_id", "event_time", "event_type", "amount"], [
        {"customer_id": f"MISLEADING-{index:02d}", "event_id": f"EV{index:02d}",
         "user_id": f"U{index % 4:02d}", "event_time": f"2025-05-{index:02d}T10:00:00",
         "event_type": ("view", "click")[index % 2], "amount": index + 1}
        for index in range(1, 13)]))

    return cases
