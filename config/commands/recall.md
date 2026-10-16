---
description: Search Anvil memory for relevant prior context
agent: anvil
---

Search Anvil memory narrowly for the user's request:

$ARGUMENTS

Use the `anvil-memory` skill and installed helper:

```sh
python3 "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/scripts/memory.py" recall "$ARGUMENTS"
```

Summarize only the strongest relevant entries. Use status, confidence, aliases, evidence and provenance to qualify each claim. Preserve any `potentially stale` warning from the helper; a registered source changed or went missing, so recheck it before relying on the memory. Treat memory as context, not proof; current repository and official source evidence takes precedence. If nothing relevant is found, say so plainly. Never dump the memory directory and never write or update memory during recall.
