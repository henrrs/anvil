"""Stateless intent and analytical intelligence contracts for Anvil."""

from .contracts import select_depth, validate_analysis_plan, validate_semantic_model, validate_task_brief
from .errors import AnalysisError
from .findings import rank_materiality, validate_result
from .investigation import validate_claims, validate_hypotheses
from .primitives import execute_plan
from .profiling import profile_file
from .semantic import infer_semantic_context, validate_semantic_context
from .statistics import compare_values, distribution_statistics, quantile

__all__ = [
    "AnalysisError", "execute_plan", "profile_file", "rank_materiality", "select_depth",
    "validate_analysis_plan", "validate_result", "validate_semantic_model", "validate_task_brief",
    "compare_values", "distribution_statistics", "infer_semantic_context", "quantile",
    "validate_claims", "validate_hypotheses", "validate_semantic_context",
]
