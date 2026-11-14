def render_status(name, state, details=None):
    if state not in {"ready", "busy", "failed"}:
        raise ValueError("unsupported status")
    suffix = "" if not details else " " + ", ".join(f"{key}={value}" for key, value in details.items())
    return f"{name}: {state}{suffix}"
