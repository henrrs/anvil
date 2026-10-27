from dataclasses import dataclass


@dataclass(frozen=True)
class Job:
    id: str
    kind: str
    payload: str
    max_attempts: int = 2

    def __post_init__(self):
        if not self.id or not self.kind or self.max_attempts < 1:
            raise ValueError("invalid job")
