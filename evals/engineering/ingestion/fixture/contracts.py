from dataclasses import dataclass


@dataclass(frozen=True)
class LoadContract:
    source: str
    dataset: str
    key: str
    mode: str = "append"
