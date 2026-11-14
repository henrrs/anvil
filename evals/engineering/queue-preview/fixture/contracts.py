from dataclasses import dataclass


@dataclass(frozen=True)
class Job:
    id: str
    handler: str
    payload: str
    retry_limit: int = 2

    def __post_init__(self):
        if not self.id or not self.handler or not isinstance(self.payload, str):
            raise ValueError("job identity, handler and payload are required")
        if not isinstance(self.retry_limit, int) or self.retry_limit < 1:
            raise ValueError("retry_limit must be a positive integer")
