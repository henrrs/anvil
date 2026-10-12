---
description: Save explicitly requested durable context to Anvil memory
agent: anvil
---

The user explicitly requested that this information be remembered:

$ARGUMENTS

Use the `anvil-memory` skill. Reject obviously ephemeral information unless the user explicitly insists. Search memory for likely duplicates first; update the closest equivalent entry rather than creating a duplicate. Normalize the durable fact, decision, lesson, or project context, keep it concise, and retain provenance honestly. Do not claim a file, URL, commit, or test as provenance unless it was actually observed.

Use the installed helper at `"${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/memory.py"`. Search with:

```sh
python3 "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/memory.py" search "relevant words"
```

Then send one JSON object to its `write-json` action on stdin. Required fields are `id`, `type` (`fact`, `decision`, `lesson`, or `project`), `scope` (for example `company` or `project:short-name`), `tags` (array), `source` (object with an honest `type`), `confidence`, and `body`. For this command, use `source.type: user-explicit` unless the user supplied a source document or repository evidence is directly relevant. Use a short safe ID. Serialize with Python's `json.dumps` rather than shell interpolation:

```sh
python3 - <<'PY' | python3 "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/memory.py" write-json
import json
print(json.dumps({
    "id": "short-memory-id",
    "type": "fact",
    "scope": "company",
    "tags": ["topic"],
    "source": {"type": "user-explicit", "note": "User invoked /remember"},
    "confidence": "confirmed",
    "body": "Concise durable information."
}))
PY
```

Report the entry path and whether it was created or updated. Do not write unrelated information.
