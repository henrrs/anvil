# SE-04 — Read the dispatcher contracts before extending it

Add a read-only queue preview to this existing local dispatcher. Preserve the current
`Job`, `Ledger`, `select_ready`, `execute_one`, and `deliver_batch` interfaces and all
retry/acknowledgement behavior.

Add `preview_batch(jobs, ledger, capacity)` in `service.py`. It returns a mapping with
`ready` (ordered job IDs), `skipped` (ordered `{id, reason}` records), and `capacity`.
Use the reasons `COMPLETED`, `RETRY_BUDGET_EXHAUSTED`, and `CAPACITY`. A job is completed
when its ID is in `ledger.completed`; it is exhausted when its failed attempt count has
reached `retry_limit`; otherwise it is ready until capacity is filled, then skipped for
capacity. Validate capacity as a positive integer. Preview must be deterministic,
side-effect-free, and must never call a handler. Reuse existing policy and contract
boundaries where appropriate; do not add a queue framework or persistence layer.

Run the public tests and add focused tests for ordering and non-mutation. Explain how
you verified that preview did not alter later delivery behavior.
