"""Failures for bounded, deterministic analysis contracts."""


class AnalysisError(ValueError):
    def __init__(self, code: str, message: str, *, remediation: str | None = None):
        super().__init__(message)
        self.code = code
        self.remediation = remediation
