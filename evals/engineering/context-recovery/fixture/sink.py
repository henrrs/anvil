class DurableSink:
    def __init__(self):
        self.records = {}
        self.commits = 0

    def commit(self, event):
        self.records.setdefault(event.id, event.payload)
        self.commits += 1
        return event.id
