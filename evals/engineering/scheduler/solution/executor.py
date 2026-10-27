class Ledger:
    def __init__(self):
        self.completed = set()
        self.attempts = {}


def execute(job, handlers, ledger):
    if job.id in ledger.completed:
        return
    if ledger.attempts.get(job.id, 0) >= job.max_attempts:
        raise ValueError("retry budget exhausted")
    ledger.attempts[job.id] = ledger.attempts.get(job.id, 0) + 1
    handlers[job.kind](job.payload)
    ledger.completed.add(job.id)
