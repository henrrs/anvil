from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    ranges: tuple
    max_connections: int


class FileSource:
    def __init__(self, rows):
        self.rows = rows
        self.reads = []

    def profile(self):
        return Profile(tuple(range(len(self.rows))), 2)

    def read(self, unit):
        self.reads.append(unit)
        return [dict(self.rows[unit])]


class FakeSqlServerSource(FileSource):
    def profile(self):
        return Profile(tuple(range(len(self.rows))), 1)
