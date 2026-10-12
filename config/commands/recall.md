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

Summarize only the strongest relevant entries. Include provenance and confidence when they affect trust or freshness. Treat memory as context, not proof; current repository and official source evidence takes precedence. If nothing relevant is found, say so plainly. Never dump the memory directory and never write or update memory during recall.
