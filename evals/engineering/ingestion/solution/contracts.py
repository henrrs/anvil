from dataclasses import dataclass


@dataclass(frozen=True)
class LoadContract:
    source: str
    dataset: str
    key: str
    mode: str = "append"

    def __post_init__(self):
        if not self.source or not self.dataset or not self.key or self.mode not in {"append", "upsert"}:
            raise ValueError("invalid load intent")
