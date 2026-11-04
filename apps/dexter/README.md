# Dexter

Dexter is a local-first, AI-assisted data engineering platform concept. This directory contains a standalone interactive frontend mock for exploring its workflows without Anvil, OpenCode, Databricks, corporate credentials, or external services.

See [PRODUCT_GUIDE.md](PRODUCT_GUIDE.md) for the product concepts, interface map, user journey, usability approach, and prototype limitations.

> All connections, data movement, SQL and notebook execution, Lab lifecycle actions, CI checks, and Pull Requests are deterministic browser-side simulations. No real data is copied and no external system is contacted.

## Start locally

From this directory, run:

```bash
python3 -m http.server 4173
```

Open [http://localhost:4173](http://localhost:4173) in a desktop browser. The demo has no install step or third-party JavaScript dependencies. State is stored in this browser's local storage; use **Settings → Reset demo** to restore the seeded data.

## Main experiences

- **Home and Workspaces:** project overview, recent work, favorites, and quick creation.
- **Discover:** shared LOCAL, DEV, and PROD catalog; table workbench; schema comparison; synthetic data; local snapshots; and a policy-aware movement wizard.
- **Build:** multi-service Development Lab composer, schemas and mock behavior, notebooks, SQL, visual pipelines, orchestration, target previews, executions, and certification.
- **Data Products:** compose products from shared assets, pipelines, contracts, output ports, consumers, and SLOs.
- **Operate and Govern:** operations, logs, lineage, contracts, quality, and profiling.
- **Deliver:** repository browsing, artifact diffs, a guided simulated PR, and delivery status.
- **Ask Dexter:** persistent assistant conversation with explicitly attached workspace context.

The mock shares one browser-side domain state across modules. Generated datasets, completed materializations, saved Labs, pipeline runs, product links, and PR records appear in their related experiences.

## Checks

```bash
node tests/smoke.mjs
```

A browser-level pass is available when Firefox and geckodriver are installed. Start geckodriver in one terminal:

```bash
geckodriver --host 127.0.0.1 --port 4444
```

Then run the check from this directory in another terminal:

```bash
python3 tests/browser_smoke.py
```

The browser check exercises the main cross-module journeys and shell layouts from 500 to 3840 pixels, including the CSS breakpoint edges. It checks open and closed sidebars, the Ask Dexter drawer, page-level horizontal overflow, compact layouts across representative screens, and saves screenshots under `/tmp/dexter-smoke/`.

## Extending the prototype

- Add screens and module navigation in `src/data.js`.
- Add screen rendering in `src/views.js` and register it in `renderScreen`.
- Add state transitions and browser persistence in `src/app.js`.
- Keep external integrations simulated until a separately designed backend exists.

The application is isolated under `apps/dexter/`; it does not change Anvil's runtime or installation behavior.
