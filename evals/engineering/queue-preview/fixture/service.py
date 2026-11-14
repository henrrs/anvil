from executor import execute_one
from policy import select_ready


def deliver_batch(jobs, handlers, ledger, capacity):
    results = []
    for job in select_ready(jobs, ledger, capacity):
        try:
            execute_one(job, handlers, ledger)
        except Exception as exc:
            results.append((job.id, "FAILED", type(exc).__name__))
        else:
            results.append((job.id, "COMPLETED", None))
    return results
