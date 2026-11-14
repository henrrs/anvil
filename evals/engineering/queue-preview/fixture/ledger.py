class Ledger:
    def __init__(self):
        self.completed = set()
        self.attempts = {}

    def acknowledge(self, job_id):
        self.completed.add(job_id)

    def failed(self, job_id):
        self.attempts[job_id] = self.attempts.get(job_id, 0) + 1
