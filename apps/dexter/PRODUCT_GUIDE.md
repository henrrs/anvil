# Dexter Product Mock Guide

## Purpose

Dexter is presented here as a local-first engineering workspace for teams that need to build and validate data solutions when their corporate development environment is incomplete. The prototype brings discovery, local development, governance, and delivery into one continuous product experience.

The mock is for evaluating product concepts, workflows, and information architecture before implementing service integrations. It is not a production data platform and does not connect to enterprise systems.

## Product idea

The experience follows one central idea: **an engineer should be able to work from an asset or a business outcome, assemble the development context they need, and move toward a reviewable delivery without first acquiring every production dependency.**

Dexter represents this as a connected path:

**Discover → Prepare locally → Compose → Develop → Validate → Package → Review**

The product combines familiar capabilities from a data catalog, local development environment, SQL and notebook workbench, pipeline builder, orchestration designer, governance console, and delivery workflow. These are modules in one workspace rather than separate prototype pages: they share assets, workspaces, pipelines, products, operations, and assistant context.

## Key concepts

### Workspaces

A workspace is the project boundary for related assets, Labs, notebooks, pipelines, tests, and delivery work. The active workspace remains visible in the top bar and informs the explorer, editor tabs, and contextual assistant.

### Environments and runtimes

The environment selector distinguishes **LOCAL**, **DEV**, and **PROD** data. LOCAL represents a development ecosystem, not a single query engine: the mock includes DuckDB, Python, a PySpark concept, and service components such as databases, Kafka, APIs, and storage. Runtime labels communicate the execution context currently represented by a screen.

### Data assets

Tables and datasets are shared catalog objects with an environment, owner, classification, schema, freshness, and local-copy state. Discovery, table inspection, SQL, notebooks, products, and lineage refer to these same assets. A materialized LOCAL dataset retains a link to its source so the user can understand where it came from.

### Development Labs

A Lab is a composable local topology. Engineers can start from a template or add database, streaming, API, storage, and processing components, then configure schemas, endpoints, and mock behavior. The Lab cockpit represents lifecycle and health feedback for that topology.

### Logical pipelines and orchestration

Pipelines describe data movement and transformations as connected nodes. Orchestration describes task dependencies, triggers, schedules, retry policies, and failure behavior. A target adapter can preview how the same logical workflow might be represented in Airflow, Azure Data Factory, or Databricks Workflows.

### Contracts, quality, and data products

Contracts describe expectations for fields and outputs. Quality and certification screens communicate whether those expectations and selected checks pass. A data product groups shared assets, pipelines, contracts, output ports, consumers, and service-level objectives into a governed unit.

### Contextual assistance

Ask Dexter is a persistent assistant surface. The user chooses when to attach the current workspace or selected assets, making shared context visible and deliberate. Replies are scripted examples in this mock, not responses from a connected model.

## Interface elements

The persistent shell is organized around the engineer's working context:

- **Top bar:** active workspace, data environment, runtime, global search, operations, notifications, and user profile.
- **Primary navigation rail:** moves among Home, Workspaces, Discover, Build, Data Products, Operate, Deliver, Govern, and Settings.
- **Workspace explorer:** exposes module-specific experiences, current project objects, and quick-create actions.
- **Editor tabs:** keep several open work areas accessible and identify the active screen.
- **Central work area:** presents the selected workflow, editor, graph, catalog, or review surface.
- **Context panel:** provides Ask Dexter, object properties, and activity beside the current work.
- **Status bar:** keeps local workspace and runtime status in view.
- **Dialogs and toasts:** support short creation, confirmation, and feedback interactions without leaving the current flow.

The shell stays consistent while the central work area changes. This lets a user move between related tasks without losing project orientation or assistant context.

## Module map

### Home and Workspaces

Home summarizes active operations, attention items, recent workspaces, local runtimes, pending reviews, and the shared data landscape. Workspaces show project details and connected assets, Labs, notebooks, and pipelines.

### Discover

Discover contains the shared asset catalog, table workbench, schema comparison, synthetic-data generation, local-data snapshots, and a guided movement flow. The intended experience is to inspect metadata and policy before preparing data for local development.

### Build

Build includes the Lab gallery and composer, schema and mock-behavior designers, Lab resources and cockpit, SQL workspace, notebook studio, visual pipeline designer, orchestration designer, target artifact preview, execution console, and test center.

### Data Products

The catalog and builder connect existing assets, pipelines, contracts, output ports, consumers, and freshness objectives. Product links also appear in shared lineage views.

### Operate and Govern

Operations and execution screens show simulated progress, logs, and failures. Lineage, contracts, quality, and profiling surfaces explain dependencies and data expectations.

### Deliver

Repository browsing, artifact review, and the PR wizard represent selecting a destination, inspecting proposed changes, running checks, and opening a simulated pull request.

### Ask Dexter

The assistant conversation persists across module navigation. Context attachments are shown explicitly so the user can see which workspace or assets are being shared with the mock assistant.

## Example user journey

The primary journey demonstrates how an engineer can go from an unavailable production dependency to a reviewable change:

1. **Open a workspace.** Review project status and choose a data environment.
2. **Find an authorized source.** Browse PROD or DEV assets and inspect schema, ownership, classification, and sample data.
3. **Prepare development data.** Use the movement flow to represent a policy-aware local snapshot, or generate synthetic data from a schema when source records should not be copied.
4. **Compose a Lab.** Start from a template or combine local database, Kafka, API, storage, and processing components. Import a schema and select a behavior profile for failure or drift scenarios.
5. **Develop against the local context.** Query the selected LOCAL asset in SQL or use it in a notebook. Build a pipeline that connects sources, transforms, checks, and destinations.
6. **Define execution behavior.** Create orchestration dependencies, schedules, retry rules, and a target-specific artifact preview.
7. **Validate the result.** Review contracts, lineage, quality checks, and certification readiness. Failed checks remain visible as blockers.
8. **Package a data product.** Associate reusable assets, pipelines, contracts, consumers, and service objectives.
9. **Prepare delivery.** Select a repository, inspect generated artifact changes, run the simulated delivery flow, and view the resulting PR record.
10. **Ask for contextual help.** Attach selected workspace context and use the scripted conversation while moving between modules.

Each step is also explorable on its own. Quick-create controls and related-object actions offer shorter paths into Labs, notebooks, pipelines, products, and asset workbenches.

## Usability approach

- **Keep orientation persistent:** the active workspace, environment, navigation, tabs, and status stay available around the main work surface.
- **Keep related work close:** properties and assistant context sit beside the editor instead of replacing it.
- **Make object relationships visible:** shared assets and pipeline references appear in products, SQL, notebooks, workspaces, and lineage.
- **Show feedback for actions:** simulations expose operation state, progress, logs, validation results, and delivery status.
- **Make context intentional:** assistant attachments are visible and can be removed by the user.
- **Support different screen sizes:** wide screens preserve the full workspace shell; Full HD uses a more compact shell and pipeline graph; narrower desktop screens reduce side panels; tablet and mobile widths switch to a focused single-work-area layout.
- **Preserve local exploration:** demo changes remain in browser storage and can be returned to the seeded state from Settings.

## Interaction and state model

The application is a standalone browser prototype implemented with HTML, CSS, and JavaScript modules. It does not require a package installation or third-party JavaScript framework. A shared client-side state powers navigation and cross-module references. Browser local storage preserves workspace edits, generated mock assets, completed operations, products, pipeline changes, chat history, and open tabs between reloads.

Actions update the mock state and render the corresponding result: for example, a completed local materialization becomes an asset in the catalog, a pipeline run appears in operations, and a saved product is visible in lineage. Simulated progress and outcomes are deterministic examples intended to make the user flow tangible.

## What is and is not real

The prototype makes no network calls to corporate data platforms, Git providers, model APIs, or runtime services. It does not copy real data, start containers or kernels, execute SQL against a database, publish artifacts, or create an actual Pull Request. Tables, query results, runtime health, operations, tests, and assistant responses are representative local mock data.

The mock validates product direction and UX flow. Authentication, authorization, policy enforcement, backend persistence, real runtime management, query execution, artifact generation, and external integrations require separate production designs and implementations.

## Run the mock

From the `apps/dexter/` directory:

```bash
python3 -m http.server 4173
```

Open [http://localhost:4173](http://localhost:4173). See [`README.md`](README.md) for smoke-check and browser-check instructions, and for the main extension points in `src/data.js`, `src/views.js`, and `src/app.js`.

## Relationship to Anvil

Dexter is an isolated product concept under `apps/dexter/`. It does not alter Anvil's installer, managed OpenCode configuration, runtime, or lifecycle behavior. The standalone mock can be opened without Anvil or OpenCode installed.
