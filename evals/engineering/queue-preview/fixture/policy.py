from contracts import Job


def select_ready(jobs, ledger, capacity):
    if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
        raise ValueError("capacity must be a positive integer")
    if not all(isinstance(job, Job) for job in jobs):
        raise ValueError("jobs must contain Job values")
    return [job for job in jobs if job.id not in ledger.completed and
            ledger.attempts.get(job.id, 0) < job.retry_limit][:capacity]
