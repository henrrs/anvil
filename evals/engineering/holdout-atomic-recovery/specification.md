# Holdout — Publish settings atomically

Keep the public `load_settings(path)` and `save_settings(path, updates)` functions
in `settings.py`. Missing files load the stable defaults. Saving merges updates
over the existing mapping, preserves unrelated keys, writes deterministic JSON,
and publishes with `os.replace` from a temporary file in the same directory. If publication
fails, the prior file must remain byte-for-byte intact and temporary files must
be cleaned up. Reject non-mapping updates. Use only the standard library.

Run `python3 -m unittest discover -s tests`. Do not add a database or service.
