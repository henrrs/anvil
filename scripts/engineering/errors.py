"""Actionable failures without private reasoning or raw process output."""

from __future__ import annotations


class EngineeringError(ValueError):
    def __init__(self, code: str, message: str, next_step: str | None = None):
        super().__init__(message)
        self.code = code
        self.next_step = next_step or {
            "WORK_STATE_STALE": "Run resume, inspect changed evidence, then revalidate or replan before continuing.",
            "WORK_STATE_UNSUPPORTED": "Use a helper supporting this task schema; do not downgrade or recover over newer state.",
            "REQUIREMENT_CONFLICT": "Review the changed specification/scope, normalize affected requirements and replan with authorization where required.",
            "BLOCKED_DEPENDENCY": "Verify prerequisites or revise the dependency model from new evidence.",
            "VERIFICATION_FAILED": "Resolve coverage, completion, architecture or unknown blockers before completing.",
            "REPEATED_FAILED_ACTION": "Inspect discriminating evidence and revise the relevant hypothesis or conditions before retrying.",
        }.get(code, "Review the named task and retry with corrected evidence.")
