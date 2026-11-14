from contracts import Job


def execute_one(job, handlers, ledger):
    if not isinstance(job, Job):
        raise ValueError("job must be a Job")
    if job.id in ledger.completed:
        return "COMPLETED"
    if ledger.attempts.get(job.id, 0) >= job.retry_limit:
        raise ValueError("job retry budget exhausted")
    handler = handlers.get(job.handler)
    if handler is None:
        raise ValueError("unknown handler")
    try:
        handler(job.payload)
    except Exception:
        ledger.failed(job.id)
        raise
    ledger.acknowledge(job.id)
    return "COMPLETED"
