#!/usr/bin/env python3
"""Format OpenCode's native JSON usage statistics without storing telemetry."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any


def timestamp(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "unknown"
    return datetime.fromtimestamp(value / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def number(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) else 0


def model_name(value: Any) -> str:
    if not isinstance(value, dict):
        return "unknown model"
    return f"{value.get('providerID', 'unknown')}/{value.get('modelID', 'unknown')}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.days < 0:
        parser.error("days must be zero or greater")
    try:
        report = json.load(sys.stdin)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR OpenCode returned invalid statistics JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(report, dict):
        print("ERROR OpenCode statistics must be a JSON object", file=sys.stderr)
        return 1
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    tokens = report.get("tokens", {})
    tokens = tokens if isinstance(tokens, dict) else {}
    cache = tokens.get("cache", {})
    cache = cache if isinstance(cache, dict) else {}
    input_tokens = number(tokens.get("input"))
    output_tokens = number(tokens.get("output"))
    reasoning_tokens = number(tokens.get("reasoning"))
    print(f"OpenCode usage (last {args.days} day(s))")
    date_range = report.get("range", {})
    if isinstance(date_range, dict):
        print(f"  period          {timestamp(date_range.get('from'))} to {timestamp(date_range.get('to'))}")
    print(f"  sessions        {number(report.get('sessions'))}")
    print(f"  input tokens    {input_tokens:,}")
    print(f"  output tokens   {output_tokens:,}")
    print(f"  reasoning       {reasoning_tokens:,}")
    print(f"  total tokens    {input_tokens + output_tokens + reasoning_tokens:,}")
    print(f"  cache read      {number(cache.get('read')):,}")
    print(f"  cache write     {number(cache.get('write')):,}")
    cost = report.get("cost")
    print(f"  cost            {'$' + format(float(cost), '.6f') if isinstance(cost, (int, float)) else 'unavailable'}")
    models = report.get("models", [])
    if isinstance(models, list) and models:
        print("Model breakdown")
        for item in models:
            if not isinstance(item, dict):
                continue
            usage = item.get("tokens", {}) if isinstance(item.get("tokens"), dict) else {}
            cache_usage = usage.get("cache", {}) if isinstance(usage.get("cache"), dict) else {}
            print(
                f"  {model_name(item.get('model'))}: steps={number(item.get('steps'))}, "
                f"input={number(usage.get('input')):,}, output={number(usage.get('output')):,}, "
                f"reasoning={number(usage.get('reasoning')):,}, "
                f"cache-read={number(cache_usage.get('read')):,}, "
                f"cache-write={number(cache_usage.get('write')):,}, "
                f"cost={'$' + format(float(item['cost']), '.6f') if isinstance(item.get('cost'), (int, float)) else 'unavailable'}"
            )
    else:
        print("Model breakdown  no recorded usage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
