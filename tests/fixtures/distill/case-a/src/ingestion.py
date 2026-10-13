def retry_delay(attempt, base=0.5, maximum=30.0):
    """Active ingestion retry path: bounded exponential backoff with jitter."""
    import random
    return min(maximum, base * (2 ** attempt)) * random.uniform(0.8, 1.2)
