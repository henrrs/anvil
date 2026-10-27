def ready(jobs, ledger, limit):
    if limit < 1:
        raise ValueError("invalid admission bound")
    return [job for job in jobs if job.id not in ledger.completed and
            ledger.attempts.get(job.id, 0) < job.max_attempts][:limit]
