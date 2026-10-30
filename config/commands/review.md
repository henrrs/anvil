---
description: Review an existing artifact or artifact plan for evidence, quantitative, narrative, structure, accessibility, and layout issues
agent: anvil
---

Review the explicitly named artifact or plan:

$ARGUMENTS

Use the `anvil-communication` skill. Do not recursively search for artifacts or edit the source. If a local Markdown artifact is supplied, run the deterministic review helper with its plan if available, then read the artifact and review the argument semantically. For SVG, validate the semantic architecture model when available; without it, say layout semantics were not verified. For unsupported formats, state the scope that could not be checked rather than implying review.

If a plan is supplied, run the local `critique PLAN.json` helper when available. Treat its candidate signals as review prompts, not automatic failures. Return actionable findings with severity, location, evidence, and a concrete correction. Check the user's audience and constraints, claim provenance, epistemic labels, counter-evidence, alternatives, materiality, calculations, percentage points, projections, units, missing values, causality, distribution, visual hierarchy, semantic representation, motion purpose, geometry, title-only storyline, accessibility, and artifact structure as applicable. Keep supported facts separate from review judgment. Do not reveal hidden chain-of-thought. Do not rewrite the file unless the user explicitly asks for edits.
