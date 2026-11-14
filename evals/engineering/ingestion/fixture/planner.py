from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    dataset: str
    units: tuple
    runtime: str
    parallelism: int


def choose(contract, profile, capabilities):
    # Starter behavior accidentally couples source pressure to runtime choice.
    runtime = "databricks" if profile.max_connections == 1 else "local"
    return Plan(contract.dataset, profile.ranges, runtime, profile.max_connections)
