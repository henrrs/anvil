from dataclasses import dataclass


@dataclass(frozen=True)
class Event:
    sequence: int
    id: str
    payload: str

    def __post_init__(self):
        if not isinstance(self.sequence, int) or self.sequence < 1 or not self.id:
            raise ValueError("event sequence and identity are required")
