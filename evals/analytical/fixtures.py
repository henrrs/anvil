"""Deterministic synthetic fixtures and evaluator-only hidden ground truth.

This module is deliberately outside ``scripts/analysis``. Production modules
must never import it, and model workspaces receive only the generated CSV.
"""

from __future__ import annotations

import csv
import json
import os
import random
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

try:
    from . import FIXTURE_VERSION
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from evals.analytical import FIXTURE_VERSION


FIXED_SEEDS = {"operations-v1": 21414, "services-v1": 21415}
FIXTURE_IDS = tuple(FIXED_SEEDS)
PERIODS = tuple(f"2025-{month:02d}" for month in range(1, 9))


def _money(value: Decimal | int | float) -> str:
    number = Decimal(str(value))
    return format(number.normalize(), "f") if number else "0"


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    if not rows:
        raise ValueError("synthetic fixture cannot be empty")
    fields = list(rows[0])
    from io import StringIO
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _entity(segment: str, number: int) -> dict[str, str]:
    if number <= 10:
        return {"segment": "bronze", "region": "north", "base_quality": "50"}
    if number <= 20:
        return {"segment": "silver", "region": "south", "base_quality": "80"}
    return {"segment": "gold", "region": "south", "base_quality": "100"}


def _operations_rows() -> list[dict[str, Any]]:
    seed = FIXED_SEEDS["operations-v1"]
    rng = random.Random(seed)
    entity_bias = {number: Decimal(rng.randrange(-20, 21)) / Decimal(100) for number in range(1, 25)}
    product_bias = {"alpha": Decimal("-0.4"), "beta": Decimal("0.4")}
    rows: list[dict[str, Any]] = []
    for period_index, period in enumerate(PERIODS):
        population = list(range(1, 21)) if period_index < 7 else [*range(5, 21), *range(21, 25)]
        for entity_number in population:
            entity_id = f"E{entity_number:02d}"
            semantic = _entity("", entity_number)
            for product_index, product in enumerate(("alpha", "beta")):
                row_number = len(rows) + 1
                quality = (Decimal(semantic["base_quality"]) + entity_bias[entity_number]
                           + product_bias[product] + Decimal(period_index) * Decimal("0.2"))
                if period_index == 7 and 5 <= entity_number <= 20:
                    quality += Decimal("1.5")
                units = Decimal(20 + entity_number * 2 + product_index * 5 + rng.randrange(0, 4))
                if period_index == 7 and 5 <= entity_number <= 20:
                    units += Decimal(5)
                    if entity_number == 15:
                        units += Decimal(500)
                    elif entity_number == 16:
                        units += Decimal(300)
                base_response = Decimal(100 if entity_number <= 10 else 300)
                if period_index == 7:
                    if 5 <= entity_number <= 12:
                        response = Decimal(50)
                    elif entity_number in {15, 16}:
                        response = Decimal(850)
                    else:
                        # A stable mean masks simultaneous improvement in part of
                        # the population and a sharply worse upper tail.
                        response = Decimal(190)
                else:
                    response = base_response
                covered = 1 if period_index < 7 or entity_number <= 12 else None
                temperature = (Decimal(15 + period_index * 2)
                               + (Decimal(semantic["base_quality"]) - Decimal(50)) / Decimal(5)
                               + Decimal(entity_number % 5) / Decimal(10))
                rows.append({
                    "event_id": f"OP{row_number:04d}", "entity_id": entity_id,
                    "region": semantic["region"], "segment": semantic["segment"],
                    "product": product, "period": period,
                    "quality_score": _money(quality), "output_units": _money(units),
                    "response_ms": _money(response), "covered": "" if covered is None else covered,
                    "eligible": 1, "ambient_index": _money(temperature),
                    "noise_score": _money(Decimal(rng.randrange(0, 1000)) / Decimal(1000)),
                })
    return rows


def _services_rows() -> list[dict[str, Any]]:
    seed = FIXED_SEEDS["services-v1"]
    rng = random.Random(seed)
    periods = tuple(f"2025-{month:02d}" for month in range(1, 7))
    rows: list[dict[str, Any]] = []
    for period_index, period in enumerate(periods):
        active = list(range(1, 17)) if period_index < 5 else [*range(3, 17), 17, 18]
        for service_number in active:
            service_id = f"S{service_number:02d}"
            event_count = 2 + (service_number + period_index) % 3
            for event_number in range(event_count):
                zone = ("east", "central", "west")[(service_number + event_number) % 3]
                category = ("deploy", "request", "incident")[(event_number + period_index) % 3]
                response = Decimal(20 + (service_number * 7 + event_number * 3) % 31)
                if period_index == 5 and zone == "west" and service_number % 3 == 0:
                    response += Decimal(45)
                rows.append({
                    "event_id": f"EV{len(rows) + 1:05d}", "service_id": service_id,
                    "zone": zone, "period": period, "event_kind": category,
                    "response_minutes": _money(response),
                    "work_units": str(5 + (service_number * 3 + event_number) % 17),
                    "covered": 1 if period_index < 5 or event_number == 0 else "",
                    "eligible": 1,
                    "ambient_load": _money(Decimal(25 + period_index * 3) + Decimal(rng.randrange(0, 8)) / 10),
                    "noise_index": _money(Decimal(rng.randrange(0, 100)) / 100),
                })
    return rows


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / Decimal(len(values)) if values else Decimal(0)


def _percentile(values: list[Decimal], percent: int) -> Decimal:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, (len(ordered) * percent + 99) // 100 - 1))
    return ordered[index]


def _operations_truth(rows: list[dict[str, Any]]) -> dict[str, Any]:
    as_decimal = lambda row, key: Decimal(row[key]) if row.get(key) not in (None, "") else None
    entities_by_period: dict[str, set[str]] = defaultdict(set)
    values_by_period: dict[str, dict[str, list[Decimal]]] = defaultdict(lambda: defaultdict(list))
    response_by_period: dict[str, list[Decimal]] = defaultdict(list)
    units_by_entity_period: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    covered: dict[str, int] = defaultdict(int)
    eligible: dict[str, int] = defaultdict(int)
    composite_keys = set()
    for row in rows:
        period, entity = row["period"], row["entity_id"]
        entities_by_period[period].add(entity)
        composite_keys.add((entity, period, row["product"]))
        for field in ("quality_score", "output_units", "response_ms"):
            value = as_decimal(row, field)
            if value is not None:
                values_by_period[period][field].append(value)
        response = as_decimal(row, "response_ms")
        if response is not None:
            response_by_period[period].append(response)
        units = as_decimal(row, "output_units")
        if units is not None:
            units_by_entity_period[period][entity] += units
        covered[period] += int(row["covered"] == 1 or row["covered"] == "1")
        eligible[period] += int(row["eligible"])
    first, last = PERIODS[0], PERIODS[-1]
    base, current = entities_by_period[first], entities_by_period[last]
    retained = base & current
    row_quality = {p: _mean(values_by_period[p]["quality_score"]) for p in (first, last)}
    retained_quality = []
    for entity in sorted(retained):
        old_values = [Decimal(row["quality_score"]) for row in rows if row["entity_id"] == entity and row["period"] == first]
        new_values = [Decimal(row["quality_score"]) for row in rows if row["entity_id"] == entity and row["period"] == last]
        retained_quality.append((entity, _mean(old_values), _mean(new_values)))
    old_response, new_response = response_by_period[first], response_by_period[last]
    old_units = sum(values_by_period[first]["output_units"], Decimal(0))
    new_units = sum(values_by_period[last]["output_units"], Decimal(0))
    old_groups, new_groups = units_by_entity_period[first], units_by_entity_period[last]
    deltas = {entity: new_groups.get(entity, Decimal(0)) - old_groups.get(entity, Decimal(0))
              for entity in base | current}
    total_abs = sum((abs(delta) for delta in deltas.values()), Decimal(0))
    top_two = sorted(deltas.items(), key=lambda item: abs(item[1]), reverse=True)[:2]
    temperature = [Decimal(row["ambient_index"]) for row in rows]
    quality = [Decimal(row["quality_score"]) for row in rows]
    x_mean, y_mean = _mean(temperature), _mean(quality)
    covariance = sum(((x - x_mean) * (y - y_mean) for x, y in zip(temperature, quality)), Decimal(0))
    x_var = sum(((x - x_mean) ** 2 for x in temperature), Decimal(0))
    y_var = sum(((y - y_mean) ** 2 for y in quality), Decimal(0))
    correlation = covariance / (x_var * y_var).sqrt() if x_var and y_var else Decimal(0)
    return {
        "fixture": {"id": "operations-v1", "version": FIXTURE_VERSION, "seed": FIXED_SEEDS["operations-v1"]},
        "semantics": {"observation_grain": ["entity_id", "period", "product"],
                      "entity_field": "entity_id", "time_field": "period", "dimensions": ["region", "segment", "product"],
                      "measures": ["quality_score", "output_units", "response_ms", "covered"]},
        "expected_facts": [
            {"id":"observations","metric":"observation count","value":len(rows),"unit":"rows","material":True},
            {"id":"time_periods","metric":"observed periods","value":len({r['period'] for r in rows}),"unit":"periods","material":True},
            {"id":"entities_total","metric":"unique entities represented","value":len({r['entity_id'] for r in rows}),"unit":"entities","material":True},
            {"id":"composite_observations","metric":"entity period product grain cardinality","value":len(composite_keys),"unit":"keys","material":True},
            {"id":"baseline_population","metric":"baseline population","value":len(base),"unit":"entities","period":first,"material":True},
            {"id":"current_population","metric":"current population","value":len(current),"unit":"entities","period":last,"material":True},
            {"id":"retained_population","metric":"retained population","value":len(retained),"unit":"entities","material":True},
            {"id":"entrants","metric":"population entrants","value":len(current-base),"unit":"entities","material":True},
            {"id":"exits","metric":"population exits","value":len(base-current),"unit":"entities","material":True},
            {"id":"quality_mean_base","metric":"quality score mean baseline","value":_money(row_quality[first]),"unit":"score","period":first,"material":True},
            {"id":"quality_mean_current","metric":"quality score mean current","value":_money(row_quality[last]),"unit":"score","period":last,"material":True},
            {"id":"quality_delta_reported","metric":"quality score reported mean change","value":_money(row_quality[last]-row_quality[first]),"unit":"score","material":True},
            {"id":"quality_delta_retained","metric":"quality score retained cohort change","value":_money(_mean([new-old for _,old,new in retained_quality])),"unit":"score","material":True},
            {"id":"quality_breadth","metric":"retained entities with quality improvement","value":sum(new>old for _,old,new in retained_quality),"unit":"entities","material":True},
            {"id":"response_mean_base","metric":"response mean baseline","value":_money(_mean(old_response)),"unit":"ms","period":first,"material":True},
            {"id":"response_mean_current","metric":"response mean current","value":_money(_mean(new_response)),"unit":"ms","period":last,"material":True},
            {"id":"response_p95_base","metric":"response p95 baseline","value":_money(_percentile(old_response,95)),"unit":"ms","period":first,"material":True},
            {"id":"response_p95_current","metric":"response p95 current","value":_money(_percentile(new_response,95)),"unit":"ms","period":last,"material":True},
            {"id":"coverage_base","metric":"measurement coverage baseline","value":_money(Decimal(covered[first])/Decimal(eligible[first])),"unit":"ratio","period":first,"material":True},
            {"id":"coverage_current","metric":"measurement coverage current","value":_money(Decimal(covered[last])/Decimal(eligible[last])),"unit":"ratio","period":last,"material":True},
            {"id":"output_sum_base","metric":"output units baseline total","value":_money(old_units),"unit":"units","period":first,"material":True},
            {"id":"output_sum_current","metric":"output units current total","value":_money(new_units),"unit":"units","period":last,"material":True},
            {"id":"top_two_contribution","metric":"top two entity output contribution share","value":_money(sum((abs(x[1]) for x in top_two),Decimal(0))/total_abs),"unit":"ratio","material":True},
            {"id":"ambient_association","metric":"ambient index quality score correlation","value":_money(correlation),"unit":"correlation","material":False},
        ],
        "material_findings": [
            {"id":"population-composition","description":"The population changed and the reported quality-score change is materially larger than the retained cohort movement.","importance":"HIGH","supporting_facts":["entrants","exits","quality_delta_reported","quality_delta_retained"]},
            {"id":"broad-retained-improvement","description":"Quality score improves for nearly all retained entities.","importance":"HIGH","supporting_facts":["quality_breadth","retained_population"]},
            {"id":"concentrated-output","description":"Most absolute output movement comes from a small number of entities.","importance":"HIGH","supporting_facts":["top_two_contribution","output_sum_base","output_sum_current"]},
            {"id":"stable-mean-worse-tail","description":"Response mean is stable while its upper tail and median shift materially.","importance":"HIGH","supporting_facts":["response_mean_base","response_mean_current","response_p95_base","response_p95_current"]},
            {"id":"coverage-decline","description":"Measurement coverage falls materially in the current period.","importance":"MEDIUM","supporting_facts":["coverage_base","coverage_current"]},
        ],
        "acceptable_interpretations":["Period and population mix are associated with the reported score change; the retained-cohort movement is smaller.","A few entities dominate output movement, so the aggregate is not broad-based for that measure.","Response distribution worsened in the upper tail even though its mean is stable."],
        "forbidden_claims":["Ambient index caused quality score change.","Every entity improved.","Population was unchanged.","The quality score change is entirely within-entity improvement."],
        "known_ambiguities":["Field labels are generic synthetic labels and do not establish real business definitions or units.","Ambient index and quality score share a time pattern; the fixture provides no causal intervention.","Noise score differences are intentionally irrelevant to material conclusions."],
        "evaluation_plan": _operations_plan("operations-v1", rows, PERIODS[0], PERIODS[-1]),
        "fact_bindings": {
            "observations":{"operation":"observation-count","path":[0,"value"]},
            "time_periods":{"operation":"period-count","path":[0,"value"]},
            "entities_total":{"operation":"entity-count","path":[0,"value"]},
            "composite_observations":{"operation":"grain-count","path":[0,"value"]},
            "baseline_population":{"operation":"quality-cohort","path":[0,"eligible_baseline"]},
            "current_population":{"operation":"quality-cohort","path":[0,"eligible_current"]},
            "retained_population":{"operation":"quality-cohort","path":[0,"common_entities"]},
            "entrants":{"operation":"quality-cohort","path":[0,"added_entities"]},
            "exits":{"operation":"quality-cohort","path":[0,"removed_entities"]},
            "quality_mean_base":{"operation":"quality-period","selector":{"group.period":PERIODS[0]+"-01"},"path":["value"]},
            "quality_mean_current":{"operation":"quality-period","selector":{"group.period":PERIODS[-1]+"-01"},"path":["value"]},
            "quality_delta_reported":{"operation":"quality-delta","path":[0,"delta"]},
            "quality_delta_retained":{"operation":"quality-cohort","path":[0,"like_for_like_delta"]},
            "quality_breadth":{"operation":"quality-cohort","path":[0,"increased_entities"]},
            "response_mean_base":{"operation":"response-period","selector":{"group.period":PERIODS[0]+"-01"},"path":["value"]},
            "response_mean_current":{"operation":"response-period","selector":{"group.period":PERIODS[-1]+"-01"},"path":["value"]},
            "response_p95_base":{"operation":"response-distribution","selector":{"group.period":PERIODS[0]+"-01"},"path":["statistics","p95"]},
            "response_p95_current":{"operation":"response-distribution","selector":{"group.period":PERIODS[-1]+"-01"},"path":["statistics","p95"]},
            "coverage_base":{"operation":"coverage-period","selector":{"group.period":PERIODS[0]+"-01"},"path":["coverage_ratio"]},
            "coverage_current":{"operation":"coverage-period","selector":{"group.period":PERIODS[-1]+"-01"},"path":["coverage_ratio"]},
            "output_sum_base":{"operation":"output-period","selector":{"group.period":PERIODS[0]+"-01"},"path":["value"]},
            "output_sum_current":{"operation":"output-period","selector":{"group.period":PERIODS[-1]+"-01"},"path":["value"]},
            "top_two_contribution":{"operation":"output-contribution","aggregate":"top_two_absolute_share"},
            "ambient_association":{"operation":"ambient-quality-correlation","path":[0,"pearson_r"]},
        },
    }


def _operations_plan(fixture_id: str, rows: list[dict[str, Any]], baseline: str, current: str) -> dict[str, Any]:
    from hashlib import sha256
    digest = sha256(_csv_bytes(rows)).hexdigest()
    if fixture_id == "operations-v1":
        operations = [
            {"id":"observation-count","operation":"count"},
            {"id":"period-count","operation":"distinct_count","column":"period"},
            {"id":"entity-count","operation":"distinct_count","column":"entity_id"},
            {"id":"grain-count","operation":"distinct_count","columns":["entity_id","period","product"]},
            {"id":"product-count","operation":"distinct_count","column":"product"},
            {"id":"quality-period","operation":"mean","column":"quality_score","group_by":["period"]},
            {"id":"quality-delta","operation":"delta","column":"quality_score","period_column":"period","baseline":baseline + "-01","current":current + "-01","aggregate":"mean"},
            {"id":"quality-cohort","operation":"cohort","column":"quality_score","period_column":"period","baseline":baseline + "-01","current":current + "-01","entity_column":"entity_id","aggregate":"mean"},
            {"id":"response-period","operation":"mean","column":"response_ms","group_by":["period"]},
            {"id":"response-distribution","operation":"distribution","column":"response_ms","group_by":["period"]},
            {"id":"coverage-period","operation":"coverage","column":"covered","denominator":"eligible","group_by":["period"]},
            {"id":"output-period","operation":"sum","column":"output_units","group_by":["period"]},
            {"id":"output-contribution","operation":"contribution","column":"output_units","period_column":"period","baseline":baseline + "-01","current":current + "-01","group_by":["entity_id"],"aggregate":"sum"},
            {"id":"segment-composition","operation":"composition","column":"quality_score","period_column":"period","baseline":baseline + "-01","current":current + "-01","group_by":["segment"],"aggregate":"mean"},
            {"id":"ambient-quality-correlation","operation":"correlation","x_column":"ambient_index","y_column":"quality_score"},
            {"id":"quality-trend","operation":"trend","column":"quality_score","period_column":"period","aggregate":"mean"},
            {"id":"segment-share","operation":"share","column":"output_units","group_by":["segment"]},
        ]
    else:
        periods = sorted({r['period'] for r in rows})
        baseline, current = periods[0], periods[-1]
        operations = [
            {"id":"observation-count","operation":"count"},
            {"id":"service-count","operation":"distinct_count","column":"service_id"},
            {"id":"service-zone-count","operation":"distinct_count","columns":["service_id","zone"]},
            {"id":"event-count","operation":"distinct_count","column":"event_id"},
            {"id":"period-count","operation":"distinct_count","column":"period"},
            {"id":"response-period","operation":"mean","column":"response_minutes","group_by":["period"]},
            {"id":"response-delta","operation":"delta","column":"response_minutes","period_column":"period","baseline":baseline + "-01","current":current + "-01","aggregate":"mean"},
            {"id":"service-cohort","operation":"cohort","column":"response_minutes","period_column":"period","baseline":baseline + "-01","current":current + "-01","entity_column":"service_id","aggregate":"mean"},
            {"id":"coverage-period","operation":"coverage","column":"covered","denominator":"eligible","group_by":["period"]},
            {"id":"response-distribution","operation":"distribution","column":"response_minutes","group_by":["period"]},
            {"id":"zone-composition","operation":"composition","column":"response_minutes","period_column":"period","baseline":baseline + "-01","current":current + "-01","group_by":["zone"],"aggregate":"mean"},
            {"id":"work-contribution","operation":"contribution","column":"work_units","period_column":"period","baseline":baseline + "-01","current":current + "-01","group_by":["service_id"],"aggregate":"sum"},
            {"id":"load-response-correlation","operation":"correlation","x_column":"ambient_load","y_column":"response_minutes"},
            {"id":"response-trend","operation":"trend","column":"response_minutes","period_column":"period","aggregate":"mean"},
        ]
    return {"schema_version":1,"source_sha256":digest,"depth":"DEEP",
            "primary_question":"What are the most important changes across the observed periods?",
            "questions":["How did the measures change?","Did the represented population or its composition change?","Did the distribution move beyond its average?"],
            "operations":operations,"stop_conditions":["Stop after the declared comparison, cohort, coverage, composition and distribution calculations."],
            "budgets":{"max_rows":50000,"max_groups":100}}


def _services_truth(rows: list[dict[str, Any]]) -> dict[str, Any]:
    periods = sorted({row['period'] for row in rows})
    services = {row['service_id'] for row in rows}
    service_zone = {(row['service_id'],row['zone']) for row in rows}
    event_ids = {row['event_id'] for row in rows}
    return {
        "fixture":{"id":"services-v1","version":FIXTURE_VERSION,"seed":FIXED_SEEDS["services-v1"]},
        "semantics":{"observation_grain":["event_id"],"entity_fields":["service_id"],"composite_entity_fields":["service_id","zone"],"time_field":"period","dimensions":["zone","event_kind"],"measures":["response_minutes","work_units","covered"]},
        "expected_facts":[{"id":"observations","metric":"event observations","value":len(rows),"unit":"events","material":True},
                          {"id":"services","metric":"unique services","value":len(services),"unit":"services","material":True},
                          {"id":"service_zones","metric":"service zone combinations","value":len(service_zone),"unit":"combinations","material":True},
                          {"id":"event_ids","metric":"unique event identifiers","value":len(event_ids),"unit":"events","material":True},
                          {"id":"time_periods","metric":"observed periods","value":len(periods),"unit":"periods","material":True}],
        "material_findings":[{"id":"event-vs-service","description":"Event rows substantially exceed the number of represented services.","importance":"HIGH","supporting_facts":["observations","services"]},
                             {"id":"composite-service","description":"Services appear across multiple zones; service-zone pairs are distinct from service count.","importance":"MEDIUM","supporting_facts":["service_zones","services"]}],
        "acceptable_interpretations":["Event count and service count answer different questions.","A service-zone pair may be a useful composite entity for location-specific comparisons."],
        "forbidden_claims":["Every event is a different service.","Ambient load caused response time.","A two-period comparison establishes a sustained trend."],
        "known_ambiguities":["Synthetic event distributions do not imply real service reliability semantics."],
        "evaluation_plan":_operations_plan("services-v1", rows, periods[0], periods[-1]),
        "fact_bindings": {
            "observations":{"operation":"observation-count","path":[0,"value"]},
            "services":{"operation":"service-count","path":[0,"value"]},
            "service_zones":{"operation":"service-zone-count","path":[0,"value"]},
            "event_ids":{"operation":"event-count","path":[0,"value"]},
            "time_periods":{"operation":"period-count","path":[0,"value"]},
        },
    }


def _trap_rows() -> dict[str, list[dict[str, Any]]]:
    rows: dict[str,list[dict[str,Any]]] = {}
    rows['rows-entities'] = [{"entity_id":f"U{i:02d}","period":f"2025-{month:02d}","event_id":f"e-{i}-{month}","value":i+month}
                             for i in range(1,9) for month in range(1,11)]
    rows['events-users'] = [{"event_id":f"evt-{user:03d}-{event:02d}","user_id":f"user-{user:03d}","event_type":"read" if event%2 else "write","value":event+user}
                            for user in range(1,101) for event in range(1,11)]
    rows['composite-entity'] = [{"account_id":f"A{account}","region":region,"period":f"2025-{month:02d}","value":account*10+month}
                                for account in range(1,5) for region in ("east","west") for month in range(1,4)]
    rows['changing-cohort'] = [{"entity_id":entity,"period":period,"value":value}
                               for period,values in (("2025-01",[("A",10),("B",20),("C",30),("D",40)]),
                                                     ("2025-02",[("B",22),("C",31),("D",41),("E",80)]))
                               for entity,value in values]
    distribution = {"2025-01":[0,0,10,10],"2025-02":[-30,10,10,50]}
    rows['stable-average-tails'] = [{"entity_id":f"X{i}","period":period,"value":value}
                                   for period,values in distribution.items() for i,value in enumerate(values)]
    stable_mean_distribution = {"2025-01":[0,0,10,10],"2025-02":[-30,10,10,30]}
    rows['stable-average-tails-v2'] = [{"entity_id":f"X{i}","period":period,"value":value}
                                      for period,values in stable_mean_distribution.items() for i,value in enumerate(values)]
    rows['correlation-no-causality'] = [{"period":f"2025-{i:02d}","ambient_index":i,"quality_score":2*i+(i%3)} for i in range(1,25)]
    rows['two-periods'] = [{"period":"2025-01","value":10},{"period":"2025-02","value":12}]
    return rows


def build_all() -> dict[str, dict[str, Any]]:
    operations = _operations_rows()
    services = _services_rows()
    return {
        "operations-v1":{"rows":operations,"csv":_csv_bytes(operations),"ground_truth":_operations_truth(operations)},
        "services-v1":{"rows":services,"csv":_csv_bytes(services),"ground_truth":_services_truth(services)},
    }


def trap_fixtures() -> dict[str, bytes]:
    return {name:_csv_bytes(rows) for name,rows in _trap_rows().items()}


def write_versioned_fixtures(root: str | Path) -> None:
    """Create public inputs and hidden truth once; refuse to silently rewrite a version."""
    root = Path(root)
    public = root / "fixtures"
    hidden = root / "ground_truth"
    traps = public / "traps"
    for directory in (public, hidden, traps):
        directory.mkdir(parents=True, exist_ok=True)
    def immutable_write(path: Path, content: bytes) -> None:
        if path.exists():
            if not path.is_file() or path.is_symlink() or path.read_bytes() != content:
                raise ValueError(f"fixture version is immutable; create a new fixture id/version instead of replacing {path.name}")
            return
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
    for fixture_id, item in build_all().items():
        immutable_write(public / f"{fixture_id}.csv", item['csv'])
        truth_bytes = (json.dumps(item['ground_truth'],ensure_ascii=False,indent=2)+'\n').encode('utf-8')
        immutable_write(hidden / f"{fixture_id}.json", truth_bytes)
    for fixture_id, content in trap_fixtures().items():
        immutable_write(traps / f"{fixture_id}.csv", content)


if __name__ == '__main__':
    write_versioned_fixtures(Path(__file__).parent)
