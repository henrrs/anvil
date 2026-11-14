class Source:
    def __init__(self, events=()):
        self.events = list(events)

    def page(self, after_sequence, limit):
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be positive")
        return [event for event in sorted(self.events, key=lambda item: item.sequence)
                if event.sequence > after_sequence][:limit]

    def append(self, event):
        self.events.append(event)
