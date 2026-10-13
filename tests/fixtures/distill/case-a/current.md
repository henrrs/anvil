# Current retry policy

Retries use exponential backoff with jitter and a bounded attempt count.
This policy is the current design and must be reflected in the ingestion client.
