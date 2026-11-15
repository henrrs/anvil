# Capabilities

Anvil adds focused instructions and local helpers around OpenCode 1. Model and provider selection remain OpenCode responsibilities.

## Core

- **Agent guidance:** compact shared instructions establish reliable task execution, evidence, and verification expectations.
- **Skills:** lazy task guidance for memory, data ingestion, Databricks, Spark and Delta Lake, engineering, system design, analytical work, and communication artifacts.
- **Memory:** explicit Markdown notes with provenance and source tracking. Search is bounded and read-only; durable memory changes require an explicit request.
- **Engineering:** progressive requirements, architecture, and work models for tasks that need continuity. Small edits can use the direct workflow.
- **Local analysis and communication:** deterministic profiling and evidence-aware report, outline, and diagram helpers. Model interpretation remains the agent's responsibility.

## Databricks

Databricks is optional. Anvil can install an isolated CLI, create its own profile, use supported local authentication, and validate workspace readiness with bounded calls. Existing external profiles are not adopted or modified. Databricks setup is explicit; ordinary Anvil installation does not configure a workspace.

The Databricks skill contains authentication, compute, SQL, and FinOps guidance. It requires explicit user intent for operations that can change cloud resources and favors read-only inspection.

## OpenCode runtime

The supported runtime is OpenCode 1.x. Anvil does not pin a model or provider. OpenCode retains ownership of authentication, sessions, plugins, tools, and runtime state. Runtime-native capabilities are reported according to the installed 1.x version.
