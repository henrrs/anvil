from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    dataset: str
    units: tuple
    runtime: str
    parallelism: int


def choose(contract, profile, capabilities):
    if not capabilities.get("name") or capabilities.get("parallelism", 0) < 1 or profile.max_connections < 1:
        raise ValueError("unsupported execution capacity")
    return Plan(contract.dataset, profile.ranges, capabilities["name"],
                min(profile.max_connections, capabilities["parallelism"]))
