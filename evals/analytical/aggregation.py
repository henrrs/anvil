"""Summary statistics for repeated model-backed evaluation runs."""

from __future__ import annotations

import statistics
from typing import Any


def aggregate_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    complete = [item for item in runs if item.get("status") == "COMPLETE"]
    durations = [float(item["duration_ms"]) for item in complete if isinstance(item.get("duration_ms"), (int, float))]
    token_runs = [item.get("tokens") for item in complete if isinstance(item.get("tokens"), dict)]
    tool_values = [item.get("tool_calls") for item in complete if isinstance(item.get("tool_calls"), int)]
    semantic_scores = [item.get("evaluation", {}).get("levels", {}).get("L2", {}).get("model_candidate", {}).get("score")
                       for item in complete]
    semantic_scores = [float(value) for value in semantic_scores if isinstance(value, (int, float))]
    lexical = [item.get("evaluation", {}).get("levels", {}).get("L3", {}).get("heuristic", {}).get("coverage")
               for item in complete]
    lexical = [float(value) for value in lexical if isinstance(value, (int, float))]
    return {
        "runs_requested": len(runs), "runs_completed": len(complete),
        "runs_blocked": sum(item.get("status") == "BLOCKED" for item in runs),
        "runs_unstructured": sum(item.get("status") == "UNSTRUCTURED_OUTPUT" for item in runs),
        "duration_ms": {"median": statistics.median(durations) if durations else None,
                        "min": min(durations) if durations else None, "max": max(durations) if durations else None,
                        "samples": durations},
        "tool_calls": {"median": statistics.median(tool_values) if tool_values else None,
                       "total": sum(tool_values) if tool_values else None},
        "tokens": {key: sum(value.get(key, 0) for value in token_runs) for key in ("input", "output", "total")}
                  if token_runs else None,
        "model_candidate_semantic_score": {"mean": statistics.mean(semantic_scores) if semantic_scores else None,
                                            "min": min(semantic_scores) if semantic_scores else None,
                                            "max": max(semantic_scores) if semantic_scores else None,
                                            "samples": semantic_scores},
        "provisional_lexical_discovery_coverage": {"mean": statistics.mean(lexical) if lexical else None,
                                                    "samples": lexical},
        "semantic_variance": (statistics.pvariance(semantic_scores) if len(semantic_scores) > 1 else 0.0)
                             if semantic_scores else None,
        "note": "Only observed metrics are aggregated. Missing tokens, calls, and human-reviewed quality metrics remain unavailable.",
    }
