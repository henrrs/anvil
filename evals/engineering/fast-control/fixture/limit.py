"""Local batch limit parsing; callers use this helper before paging."""


def choose_limit(requested=None, default=100, maximum=10000):
    if requested is None:
        return default
    try:
        return int(requested)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
