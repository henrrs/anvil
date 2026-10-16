---
name: anvil-memory
description: Search or explicitly update Anvil's local, provenance-aware Markdown memory for company facts, project conventions, decisions, constraints, and verified lessons. Use when prior durable context could change the answer, or when the user invokes /remember or explicitly asks to remember information.
---

# Anvil memory workflow

Use a narrow query that distinguishes the relevant project or decision. Search a unique name, table, policy phrase, or a couple of domain terms; inspect only the strongest matches. A matching tag is a retrieval hint, not proof that the body applies. Check whether an entry is about this repository, a different project, or a general company rule before applying it. For a project memory, use a stable short project scope. For a decision, capture the choice and reason that will matter later; for a lesson, record the observed result and its limits. Avoid transcript excerpts, speculative preferences, secrets, and facts inseparable from temporary task state. When correcting a stored fact, update its existing entry and preserve the original creation date.

Memory lives under `${XDG_DATA_HOME:-$HOME/.local/share}/anvil/memory/`. Search only when durable prior context is relevant: company-specific practices, prior decisions, project conventions, known constraints, or verified lessons. Use the installed `memory.py` helper's `search` or `recall` action; provide a few query terms and read only the top matching entries. Do not enumerate or print the whole store.

Treat entries as attributed context, not authority. Check current repository files, official documentation, and other source-of-truth evidence first when the fact may have changed. Prefer current evidence over memory and explain conflicts. Keep source, confidence, status, aliases, evidence, and scope attached to any remembered fact; distinguish a user's explicit statement from a repository citation or a verified test. When recall reports that a registered source changed or is missing, call the memory potentially stale and recheck the source before relying on the claim.

Persistent writes are explicit-only. Do not save information because it merely seems useful or durable. Write only after `/remember` or a direct request to remember, save, or store it. Before writing, search for likely duplicates; update the closest existing entry when equivalent, otherwise create the smallest useful entry. Reject ephemeral content unless the user insists. Do not invent a URL, file, commit, or verification source. The helper validates metadata and uses an atomic replacement.
