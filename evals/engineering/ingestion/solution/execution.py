def execute(plan, source, sink, progress):
    for unit in plan.units:
        identity = f"{plan.dataset}:{unit}"
        if identity in progress.committed:
            continue
        rows = source.read(unit)
        sink.commit(identity, rows)
        progress.commit(identity)


class LocalSink:
    def __init__(self, key):
        self.key = key
        self.landing = {}
        self.bronze = []
        self.silver = {}

    def commit(self, identity, rows):
        if identity in self.landing:
            return
        copied = [dict(row) for row in rows]
        self.landing[identity] = copied
        self.bronze.extend(copied)
        for row in copied:
            self.silver[row[self.key]] = dict(row)
