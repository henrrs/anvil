# Holdout — Preserve the status formatter API

Keep the `render_status(name, state, details=None)` function and existing output
for the default status line. Add a structured option for callers that request
JSON output with `as_json=True`, returning stable JSON with the same values.
Existing positional callers must continue to work. Do not mutate `details`, do
not import third-party packages, and reject unsupported states with `ValueError`.
Run `python3 -m unittest discover -s tests`.
