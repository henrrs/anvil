(function exposeMockAnalyticsApi(global) {
  const NOW = Date.now();
  const isoDaysAgo = (days) => new Date(NOW - days * 86_400_000).toISOString();

  const TABLES = [
    { full_name: "main.finance.transactions", object_type: "TABLE", comment: "One row per posted financial transaction.", local_state: "full" },
    { full_name: "main.finance.payment_events", object_type: "TABLE", comment: "Payment lifecycle events from processor feeds.", local_state: "partial" },
    { full_name: "main.finance.customer_accounts", object_type: "TABLE", comment: "Customer account dimensions and status.", local_state: "stale" },
    { full_name: "main.finance.daily_revenue", object_type: "VIEW", comment: "Daily recognized revenue by channel." },
    { full_name: "main.finance.refunds", object_type: "TABLE", comment: "Settled and pending refunds." },
    { full_name: "main.operations.fulfillment_events", object_type: "TABLE", comment: "Order fulfillment milestones." },
    { full_name: "main.operations.inventory_position", object_type: "TABLE", comment: "Warehouse stock position by SKU." },
    { full_name: "lakehouse.silver.web_sessions", object_type: "TABLE", comment: "Cleaned product analytics sessions." },
    { full_name: "lakehouse.gold.retention_cohorts", object_type: "VIEW", comment: "Weekly retention cohort summary." },
    { full_name: "sandbox.experiments.checkout_funnel", object_type: "TABLE", comment: "Experiment analysis snapshot." },
  ];

  const COLUMNS = [
    { name: "transaction_id", type_text: "STRING", nullable: false, comment: "Stable transaction key" },
    { name: "customer_id", type_text: "BIGINT", nullable: false, comment: "Account key" },
    { name: "event_ts", type_text: "TIMESTAMP", nullable: false, comment: "UTC event time" },
    { name: "amount_usd", type_text: "DECIMAL(18,2)", nullable: true, comment: "Signed transaction amount" },
    { name: "status", type_text: "STRING", nullable: false, comment: "Normalized lifecycle status" },
    { name: "channel", type_text: "STRING", nullable: true, comment: "Acquisition channel" },
  ];

  const ROWS = [
    ["txn_20261031_00841", 10482, "2026-10-31T10:42:18Z", 128.50, "SETTLED", "web"],
    ["txn_20261031_00840", 10917, "2026-10-31T10:39:02Z", 64.00, "SETTLED", "mobile"],
    ["txn_20261031_00839", 10126, "2026-10-31T10:33:45Z", -21.99, "REFUNDED", "web"],
    ["txn_20261031_00838", 11305, "2026-10-31T10:31:11Z", 219.00, "PENDING", "partner"],
    ["txn_20261031_00837", 10261, "2026-10-31T10:28:56Z", 42.75, "SETTLED", "mobile"],
  ];

  const WAREHOUSES = [
    { warehouse_id: "wh-serverless-analytics", name: "Serverless Analytics", state: "RUNNING", warehouse_type: "SERVERLESS", size: "Small", is_default: true },
    { warehouse_id: "wh-engineering-shared", name: "Engineering Shared", state: "RUNNING", warehouse_type: "PRO", size: "Medium" },
    { warehouse_id: "wh-bi-shared", name: "BI Warehouse", state: "STOPPED", warehouse_type: "CLASSIC", size: "Small" },
    { warehouse_id: "wh-legacy", name: "Legacy Warehouse", state: "STOPPED", warehouse_type: "CLASSIC", size: "2X-Small" },
  ];

  class MockAnalyticsApi {
    constructor(scenario = "healthy") {
      this.scenario = scenario;
      this.catalogRefreshes = 0;
      this.operationCounter = 0;
      this.operations = ["materializing", "active-operation"].includes(scenario) ? [{
        operation_id: "mat-live-01", kind: "MATERIALIZATION", state: "RUNNING",
        source_name: "main.finance.payment_events", rows: 84_200, bytes: 18_400_000,
        started_at: isoDaysAgo(0), percent: 68, planned_rows: 123_824,
        completed_rows: 84_200, completed_bytes: 18_400_000, completed_chunks: 7, total_chunks: 11,
      }] : [];
      if (["parallel-materializations", "queued-materialization"].includes(scenario)) this.operations = [
        { operation_id: "mat-a", kind: "MATERIALIZATION", state: "RUNNING", phase: "DOWNLOADING_ARROW",
          source_name: "main.finance.transactions", percent: 50, planned_rows: 4_714_788,
          completed_rows: 2_357_394, completed_bytes: 426_000_000, completed_chunks: 21, total_chunks: 42 },
        { operation_id: "mat-b", kind: "MATERIALIZATION", state: "RUNNING", phase: "WRITING_PARQUET",
          source_name: "main.finance.payment_events", percent: null,
          completed_rows: 180_000, completed_bytes: 43_000_000, completed_chunks: 2 },
        { operation_id: "mat-c", kind: "MATERIALIZATION", state: "QUEUED", phase: "QUEUED",
          source_name: "main.operations.inventory_position", percent: null },
      ];
      if (scenario === "half-progress") this.operations = [{ operation_id: "mat-half", kind: "MATERIALIZATION",
        state: "RUNNING", phase: "DOWNLOADING_ARROW", source_name: "main.finance.transactions",
        percent: 50, planned_rows: 4_714_788, completed_rows: 2_357_394,
        completed_bytes: 426_000_000, completed_chunks: 21, total_chunks: 42 }];
      if (["failed-operations", "resumable-transfer", "network-retry"].includes(scenario)) this.operations = [{
        operation_id: "mat-resume", kind: "MATERIALIZATION", state: "FAILED", phase: "RESUMABLE",
        source_name: "main.finance.transactions", percent: 13.4, planned_rows: 4_714_788,
        completed_rows: 630_784, completed_bytes: 149_200_000, completed_chunks: 7,
        total_chunks: 52, resume_available: true, failure_reason: "TRANSFER_ERROR" }];
      this.chatStorageKey = `anvil:analytics:mock-chat:${scenario}`;
      this.chatStorage = global.sessionStorage || { getItem: () => null, setItem: () => {} };
      try { this.chatMessages = JSON.parse(this.chatStorage.getItem(this.chatStorageKey) || "null"); }
      catch { this.chatMessages = null; }
      if (!Array.isArray(this.chatMessages)) this.chatMessages = scenario === "persistent-chat" ? [
        { id: 1, role: "user", content: "What changed in transactions?" },
        { id: 2, role: "assistant", content: "The latest local copy has 482,211 rows." },
        { id: 3, role: "user", content: "Is the coverage complete?" },
        { id: 4, role: "assistant", content: "Yes. All columns and rows are covered." },
      ] : [];
      this.materializationStarted = new Map();
    }

    async request(path, options = {}) {
      const url = new URL(path, global.location.origin || "http://127.0.0.1");
      const method = String(options.method || "GET").toUpperCase();
      const body = options.body ? JSON.parse(options.body) : {};
      const pathname = decodeURIComponent(url.pathname);
      const query = url.searchParams;

      if (pathname === "/api/me") return this._me();
      if (pathname === "/api/anvil/chat/history" && method === "GET") {
        const before = Number(query.get("before") || Number.MAX_SAFE_INTEGER);
        const limit = Math.min(100, Math.max(1, Number(query.get("limit") || 30)));
        const older = this.chatMessages.filter((item) => item.id < before);
        const items = older.slice(-limit);
        return { items, next_before: older.length > limit ? items[0].id : null };
      }
      if (pathname === "/api/anvil/chat/clear" && method === "POST") {
        this.chatMessages = [];
        this.chatStorage.setItem(this.chatStorageKey, JSON.stringify(this.chatMessages));
        return { cleared: true, session_id: "mock-new-thread" };
      }
      if (pathname === "/api/runtime") return this._me().status.runtime;
      if (pathname === "/api/warehouses") return this._warehouses();
      if (pathname === "/api/warehouses/refresh" && method === "POST") return this._warehouses(true);
      if (pathname.startsWith("/api/warehouses/")) {
        const id = pathname.slice("/api/warehouses/".length);
        const item = (await this._warehouses()).warehouses.find((warehouse) => warehouse.warehouse_id === id);
        if (!item) throw this._error("WAREHOUSE_NOT_FOUND", "That SQL Warehouse is no longer available.", 404);
        return item;
      }

      if (pathname === "/api/catalog" || pathname === "/api/catalog/refresh") {
        if (method === "POST") this.catalogRefreshes += 1;
        return this._page(this._catalogs(), Number(query.get("limit") || body.limit || 100),
          Number(query.get("offset") || body.offset || 0), this.scenario === "offline" ? "BROWSE_ONLY" : "READY");
      }
      if (pathname === "/api/catalog/search") return this._search(query.get("q") || "", Number(query.get("limit") || 100));
      const catalogRoute = pathname.match(/^\/api\/catalog\/([^/]+)\/schemas$/);
      if (catalogRoute) return this._page(this._schemas(catalogRoute[1]), Number(query.get("limit") || 100), Number(query.get("offset") || 0));
      const tablesRoute = pathname.match(/^\/api\/catalog\/([^/]+)\/([^/]+)\/tables$/);
      if (tablesRoute) return this._page(this._tables(tablesRoute[1], tablesRoute[2]), Number(query.get("limit") || 100), Number(query.get("offset") || 0));

      if (pathname.startsWith("/api/tables/")) return this._tableRoute(pathname.slice("/api/tables/".length), query);
      if (pathname === "/api/query/history") return { items: this._queryHistory() };
      if (pathname === "/api/operations") return { items: this.operations.map((item) => ({ ...item })) };
      if (pathname === "/api/materializations" && method === "GET") return { items: this._materializations() };
      if (pathname === "/api/datasets" && method === "GET") return { items: this._datasets() };
      if (pathname.startsWith("/api/datasets/") && method === "DELETE") {
        const datasetId = pathname.slice("/api/datasets/".length);
        this.deletedDatasets ||= new Set();
        this.deletedDatasets.add(datasetId);
        return { dataset_id: datasetId, deleted: true, removed_generations: 1 };
      }
      if (pathname === "/api/investigations/recent") return { items: this._investigations() };
      if (pathname === "/api/query/explain" && method === "POST") return this._explain(body.sql || "");
      if (pathname === "/api/query" && method === "POST") return this._query(body);
      if (pathname === "/api/materializations" && method === "POST") return this._startMaterialization(body);
      if (pathname.startsWith("/api/materializations/")) return this._materializationRoute(pathname, method);
      throw this._error("NOT_FOUND", "The mock Analytics API route was not found.", 404);
    }

    async streamChat(body, onEvent) {
      const prompt = String(body?.prompt || "").trim();
      if (!prompt) throw this._error("INVALID_REQUEST", "Ask Anvil requires a question.");
      onEvent?.("status", { message: "Preparing Analytics session…" });
      await new Promise((resolve) => global.setTimeout(resolve, 90));
      if (this.scenario === "degraded") {
        throw this._error("RUNTIME_UNAVAILABLE", "The configured OpenCode runtime is unavailable in this scenario.", 503);
      }
      onEvent?.("status", { message: "Asking Anvil in the canonical session…",
        model: { logical_model: "anvil-analytics", display_name: "Luna 6",
          provider_name: "GitHub Copilot", model_id: "luna-6-fixture" } });
      const table = body.context?.table;
      const answer = table
        ? "For " + table + ", start by checking the table grain and freshness.\n\n| Check | What to verify |\n| --- | --- |\n| Grain | One row per business key |\n| Freshness | Latest source update |\n\nThis response is fixture driven; it does not call a model."
        : "I can help you explore this Analytics workspace. Try opening a table, reviewing its local coverage, or asking how AUTO query routing chooses between DuckDB and Databricks. This response is fixture driven; it does not call a model.";
      for (let offset = 0; offset < answer.length; offset += 42) {
        const part = answer.slice(offset, offset + 42);
        onEvent?.("chunk", { text: part });
        await new Promise((resolve) => global.setTimeout(resolve, 35));
      }
      onEvent?.("done", { state: "completed", session: "mock-canonical" });
      const next = this.chatMessages.length ? this.chatMessages.at(-1).id + 1 : 1;
      this.chatMessages.push({ id: next, role: "user", content: prompt },
        { id: next + 1, role: "assistant", content: answer });
      this.chatStorage.setItem(this.chatStorageKey, JSON.stringify(this.chatMessages));
    }

    _me() {
      const offline = this.scenario === "offline";
      const degraded = this.scenario === "degraded";
      return {
        name: "Henrique Engineer", identity_source: this.scenario === "identity-degraded" ? "databricks_cache" : "databricks",
        identity_type: "user", user_name: "henrique@example.com",
        workspace: "https://adb-demo.azuredatabricks.net",
        profile: "anvil-demo", databricks_configured: true,
        status: {
          runtime: { status: degraded ? "DEGRADED" : "READY", generation: 2,
            ...(degraded ? { error: { code: "RUNTIME_UNAVAILABLE", message: "OpenCode runtime is unavailable." } } : {}) },
          model_policy: { logical_model: "anvil-analytics", display_name: "Luna 6",
            provider_preference: "github-copilot", provider_id: "github-copilot",
            provider_name: "GitHub Copilot", model_id: "luna-6-fixture", resolution: "READY", fallback: "NONE" },
          databricks: { status: offline ? "DEGRADED" : "READY", profile: "anvil-demo", workspace: "https://adb-demo.azuredatabricks.net" },
          catalog: { status: offline ? "BROWSE_ONLY" : "AVAILABLE", cached_objects: this.scenario === "large-catalog" ? 30_000 : 842 },
          local: { duckdb: "READY", pyarrow: "READY", storage_bytes: 18_400_000_000 },
          capabilities: { catalog: "AVAILABLE", sql_remote: offline ? "DEGRADED" : "READY", sql_local: "READY", ask_anvil: degraded ? "DEGRADED" : "READY", materialization: "READY" },
        },
      };
    }

    _warehouses() {
      if (this.scenario === "no-warehouses") return { status: "EMPTY", warehouses: [], refreshed_at: new Date().toISOString(), error: null };
      if (this.scenario === "warehouse-disappeared") return { status: "READY", warehouses: WAREHOUSES.filter((item) => item.warehouse_id !== "wh-serverless-analytics"), refreshed_at: new Date().toISOString(), error: null };
      const items = (this.scenario === "single-warehouse" ? WAREHOUSES.slice(0, 1) : WAREHOUSES).map((item) => ({ ...item }));
      const offline = this.scenario === "offline";
      return { status: offline ? "STALE" : "READY", warehouses: items,
        refreshed_at: isoDaysAgo(offline ? 1 : 0),
        error: offline ? { code: "WORKSPACE_UNREACHABLE", message: "Databricks is offline. Showing the last cached warehouse inventory." } : null };
    }

    _catalogs() {
      if (this.scenario === "large-catalog") {
        return Array.from({ length: 260 }, (_, index) => ({
          full_name: `workspace_${String(index + 1).padStart(3, "0")}`,
          object_type: "CATALOG", comment: `Synthetic catalog fixture ${index + 1}`,
        }));
      }
      return [
        { full_name: "main", object_type: "CATALOG", comment: "Production curated data products." },
        { full_name: "lakehouse", object_type: "CATALOG", comment: "Silver and gold lakehouse layers." },
        { full_name: "sandbox", object_type: "CATALOG", comment: "Exploration and experiment datasets." },
      ];
    }

    _schemas(catalog) {
      if (this.scenario === "large-catalog") return Array.from({ length: 130 }, (_, index) => ({
        full_name: `${catalog}.domain_${String(index + 1).padStart(3, "0")}`,
        object_type: "SCHEMA", comment: `Curated domain ${index + 1}`,
      }));
      const schemas = { main: ["finance", "operations", "customers"], lakehouse: ["silver", "gold", "product"], sandbox: ["experiments", "research"] };
      return (schemas[catalog] || ["default"]).map((name) => ({ full_name: `${catalog}.${name}`, object_type: "SCHEMA", comment: `${name[0].toUpperCase()}${name.slice(1)} analytics schema.` }));
    }

    _tables(catalog, schema) {
      if (this.scenario === "large-catalog") return Array.from({ length: 305 }, (_, index) => ({
        full_name: `${catalog}.${schema}.fact_${String(index + 1).padStart(4, "0")}`,
        object_type: index % 13 === 0 ? "VIEW" : "TABLE",
        comment: `Synthetic analytical object ${index + 1}`,
      }));
      const selected = TABLES.filter((item) => item.full_name.startsWith(`${catalog}.${schema}.`));
      return selected.length ? selected : [{ full_name: `${catalog}.${schema}.daily_summary`, object_type: "VIEW", comment: "Daily summary by business date." }];
    }

    _page(items, limit, offset, status = "READY") {
      const safeLimit = Number.isInteger(limit) ? Math.max(1, Math.min(200, limit)) : 100;
      const safeOffset = Number.isInteger(offset) ? Math.max(0, offset) : 0;
      const page = items.slice(safeOffset, safeOffset + safeLimit);
      const hasMore = safeOffset + page.length < items.length;
      return { status, items: page, error: status === "BROWSE_ONLY" ? "WORKSPACE_UNREACHABLE" : null,
        has_more: hasMore, next_offset: hasMore ? safeOffset + page.length : null };
    }

    _search(term, limit) {
      const cleaned = term.trim().toLowerCase();
      if (!cleaned) throw this._error("INVALID_REQUEST", "Enter a catalog search term.");
      let matches = TABLES.filter((item) => `${item.full_name} ${item.comment}`.toLowerCase().includes(cleaned));
      if (this.scenario === "large-catalog" && matches.length < 100) {
        matches = Array.from({ length: 120 }, (_, index) => ({ full_name: `workspace_001.domain_001.fact_${String(index + 1).padStart(4, "0")}`, object_type: "TABLE", comment: `Synthetic object matching ${cleaned}` }));
      }
      const safeLimit = Math.max(1, Math.min(200, limit || 100));
      return { status: "CACHED", parent: "", items: matches.slice(0, safeLimit), truncated: matches.length > safeLimit };
    }

    _tableRoute(suffix, query) {
      const isPreview = suffix.endsWith("/preview");
      const isCoverage = suffix.endsWith("/coverage");
      const isLineage = suffix.endsWith("/lineage");
      const isProfile = suffix.endsWith("/profile");
      const fullName = suffix.replace(/\/(preview|coverage|lineage|profile)$/, "");
      if (isPreview) return { status: "READY", columns: COLUMNS.slice(0, 5).map((column) => column.name), rows: ROWS.slice(0, 5).map((row) => row.slice(0, 5)), row_count: 5, truncated: false };
      if (isCoverage) {
        if (this.scenario === "local-needs-update" && fullName.endsWith("old_local_copy"))
          return { covered: false, state: "INVALID", reason: "Local copy needs to be updated",
            snapshot_id: "mock-invalid", columns: COLUMNS.map((column) => column.name),
            rows: 0, bytes: 12_000_000, rows_mode: "FULL", columns_mode: "ALL" };
        const local = fullName.endsWith("transactions") ? "full" : fullName.endsWith("payment_events") ? "partial" : "remote";
        const sourceIsFull = local === "full";
        const sourceIsPartial = local === "partial";
        return {
          covered: sourceIsFull,
          freshness: sourceIsFull ? "CURRENT" : "UNKNOWN",
          state: sourceIsFull ? "FULLY_COVERED" : sourceIsPartial ? "PARTIALLY_COVERED" : "NOT_COVERED",
          snapshot_id: local === "remote" ? "" : "snapshot-" + local + "-20261031",
          dataset_id: local === "remote" ? "" : sourceIsFull ? "mock-dataset-transactions" : "mock-dataset-payment-events",
          rows: local === "remote" ? 0 : sourceIsFull ? 482211 : 84200,
          bytes: local === "remote" ? 0 : sourceIsFull ? 2118342144 : 18400000,
          columns: sourceIsFull ? COLUMNS.map((item) => item.name) : ["transaction_id", "event_ts"],
          columns_mode: sourceIsFull ? "ALL" : "SELECTED",
          rows_mode: sourceIsPartial ? "FILTERED" : "FULL",
          updated_at: local === "remote" ? "" : isoDaysAgo(0.3),
          reason: sourceIsFull ? "Local copy covers the table." : sourceIsPartial
            ? "Local copy contains selected columns and filtered rows." : "No local copy is available.",
        };
      }
      if (isLineage) return { status: "READY", rows: [
        { event_time: isoDaysAgo(1), source_table_full_name: "lakehouse.silver.processor_events", target_table_full_name: fullName },
        { event_time: isoDaysAgo(2), source_table_full_name: "main.finance.customer_accounts", target_table_full_name: fullName },
      ] };
      if (isProfile) return { status: "READY", columns: COLUMNS.map((item, index) => ({ name: item.name, distinct_in_sample: [482211, 14783, 480102, 38211, 5, 4][index], null_count: index === 3 ? 812 : 0 })) };
      const table = TABLES.find((item) => item.full_name === fullName) || { full_name: fullName, object_type: "TABLE", comment: "Synthetic catalog table." };
      return { status: "CACHED", object: { ...table, owner: "analytics-engineering", updated_at: isoDaysAgo(0.2),
        properties: { table_type: table.object_type === "VIEW" ? "VIEW" : "MANAGED", data_source_format: "DELTA", owner: "analytics-engineering", partition_columns: ["event_date"] },
        columns: COLUMNS.map((item, index) => ({ ...item, position: index })) } };
    }

    _queryHistory() {
      const base = [
        { id: 91, sql_text: "SELECT status, count(*) AS transactions FROM main.finance.transactions GROUP BY status", route: "LOCAL", status: "SUCCESS", row_count: 5, created_at: isoDaysAgo(0) },
        { id: 90, sql_text: "SELECT channel, sum(amount_usd) FROM main.finance.transactions GROUP BY channel", route: "DATABRICKS", status: "SUCCESS", row_count: 4, created_at: isoDaysAgo(1) },
        { id: 89, sql_text: "SELECT * FROM main.finance.payment_events LIMIT 100", route: "DATABRICKS", status: "FAILED", error_code: "WORKSPACE_UNREACHABLE", created_at: isoDaysAgo(2) },
      ];
      return this.scenario === "many-recent" ? base.concat(Array.from({ length: 12 }, (_, index) => ({
        id: 80 - index, sql_text: `SELECT * FROM main.finance.local_table_${index} LIMIT 100`,
        route: "LOCAL", status: "SUCCESS", row_count: 100, created_at: isoDaysAgo(index + 1) }))) : base;
    }

    _materializations() {
      return [
        { materialization_id: "snap-transactions", source_name: "main.finance.transactions", state: "READY", row_count: 482_211, byte_count: 2_118_342_144, updated_at: isoDaysAgo(0.3) },
        { materialization_id: "snap-payment-events", source_name: "main.finance.payment_events", state: "READY", row_count: 84_200, byte_count: 18_400_000, updated_at: isoDaysAgo(1) },
      ];
    }

    _datasets() {
      const datasets = [
        { dataset_id: "mock-dataset-transactions", source_name: "main.finance.transactions", state: "READY",
          columns: COLUMNS.map((column) => column.name), columns_mode: "ALL", rows_mode: "FULL",
          rows: 482_211, bytes: 2_118_342_144, updated_at: isoDaysAgo(0.3) },
        { dataset_id: "mock-dataset-payment-events", source_name: "main.finance.payment_events", state: "READY",
          columns: COLUMNS.slice(0, 3).map((column) => column.name), columns_mode: "SELECTED", rows_mode: "FILTERED",
          rows: 84_200, bytes: 18_400_000, updated_at: isoDaysAgo(1) },
      ];
      if (["legacy-migrating", "many-local"].includes(this.scenario)) datasets.push({
        dataset_id: "mock-legacy", source_name: "main.finance.ied_compute_adf", state: "READY",
        columns: Array.from({ length: 37 }, (_, index) => `column_${index + 1}`),
        columns_mode: "ALL", rows_mode: "FULL", rows: 468_684, bytes: 20_971_520,
        updated_at: isoDaysAgo(0.1) });
      if (this.scenario === "local-needs-update") datasets.push({
        dataset_id: "mock-invalid", source_name: "main.finance.old_local_copy", state: "INVALID",
        columns: COLUMNS.map((column) => column.name), rows: 0, bytes: 12_000_000,
        updated_at: isoDaysAgo(1) });
      if (this.scenario === "many-local") for (let index = 0; index < 7; index++) datasets.push({
        dataset_id: `mock-local-${index}`, source_name: `main.finance.local_table_${index}`, state: "READY",
        columns: COLUMNS.map((column) => column.name), rows: 100_000 + index,
        bytes: 25_000_000 + index * 100_000, updated_at: isoDaysAgo(index) });
      return datasets.concat([...((this.localCopies || new Map()).values())])
        .filter((item) => !this.deletedDatasets?.has(item.dataset_id));
    }

    _investigations() {
      return [{ investigation_id: "inv-2026-104", title: "Refund rate anomaly", state: "COMPLETED",
        summary: "Refunds increased in mobile orders; the shift aligns with a processor retry change.", updated_at: isoDaysAgo(1) }];
    }

    _explain(sql) {
      const isLocal = !/FROM\s+(?!`?main\.)/i.test(sql) || /FROM\s+`?main\.finance\.transactions/i.test(sql);
      return { route: isLocal ? "LOCAL" : "DATABRICKS", local_coverage: isLocal,
        reason: isLocal ? "A matching local snapshot covers this read-only query." : "The selected sources require remote Databricks execution." };
    }

    _query(body) {
      const sql = String(body.sql || "");
      if (/\b(invalid|syntax_error|mock_fail)\b/i.test(sql)) throw this._error("SQL_VALIDATION_FAILED", "The mock query contains an intentional fixture error.", 400);
      if (this.scenario === "offline" && String(body.route).toUpperCase() === "DATABRICKS") throw this._error("WORKSPACE_UNREACHABLE", "Databricks is offline in this mock scenario.", 503);
      const explanation = this._explain(sql);
      const route = String(body.route || "AUTO").toUpperCase() === "AUTO" ? explanation.route : String(body.route).toUpperCase();
      return { status: "READY", route, columns: ["status", "transaction_count", "gross_amount"],
        rows: [["SETTLED", 371_029, 42_183_902.41], ["PENDING", 12_401, 1_082_271.00], ["REFUNDED", 8_781, -321_845.12]],
        row_count: 3, byte_count: 154, truncated: false, latency_ms: 84 };
    }

    _startMaterialization(body) {
      this.lastMaterializationRequest = { ...body };
      const operationId = `mock-materialize-${++this.operationCounter}`;
      const operation = { operation_id: operationId, kind: "MATERIALIZATION", state: "RUNNING",
        source_name: String(body.source_name || "main.finance.transactions"), rows: 0, bytes: 0, progress: 8,
        phase: "STARTING_WAREHOUSE" };
      this.operations.unshift(operation);
      this.materializationStarted.set(operationId, Date.now());
      return { operation_id: operationId, state: "RUNNING" };
    }

    _materializationRoute(pathname, method) {
      const suffix = pathname.slice("/api/materializations/".length);
      if (suffix.endsWith("/cancel") && method === "POST") {
        const id = suffix.slice(0, -"/cancel".length);
        const operation = this.operations.find((item) => item.operation_id === id);
        if (operation) operation.state = "CANCELLED";
        return { operation_id: id, state: "CANCELLED" };
      }
      if (suffix.endsWith("/retry") && method === "POST") {
        const id = suffix.slice(0, -"/retry".length);
        const operation = this.operations.find((item) => item.operation_id === id);
        if (!operation) throw this._error("NOT_FOUND", "Materialization was not found.", 404);
        operation.state = "RUNNING";
        operation.phase = "DOWNLOADING_ARROW";
        operation.resume_available = false;
        this.materializationStarted.set(id, Date.now());
        return { ...operation };
      }
      const id = suffix.replace(/\/(refresh)$/, "");
      const operation = this.operations.find((item) => item.operation_id === id) || {
        operation_id: id, source_name: "main.finance.payment_events", state: "RUNNING", progress: 68, rows: 84_200, bytes: 18_400_000,
      };
      const started = this.materializationStarted.get(id);
      if (started && Date.now() - started > 9000 && operation.state === "RUNNING") {
        operation.state = "READY";
        operation.phase = "ACTIVATING";
        operation.progress = 100;
        operation.rows = 100_000;
        operation.bytes = 24_100_000;
        this.materializationStarted.delete(id);
        this.localCopies ||= new Map();
        const datasetId = `mock-dataset-${encodeURIComponent(operation.source_name).replace(/%/g, "-")}`;
        this.localCopies.set(datasetId, { dataset_id: datasetId, source_name: operation.source_name,
          state: "READY", columns: COLUMNS.map((column) => column.name), columns_mode: "SELECTED",
          rows_mode: "FULL", rows: operation.rows, bytes: operation.bytes, updated_at: new Date().toISOString() });
      }
      if (started && Date.now() - started > 2800 && operation.state === "RUNNING") operation.phase = "WRITING_PARQUET";
      else if (started && Date.now() - started > 900 && operation.state === "RUNNING") operation.phase = "DOWNLOADING_ARROW";
      return { ...operation, kind: "MATERIALIZATION" };
    }

    _error(code, message, status = 503) {
      const error = new Error(message);
      error.code = code;
      error.status = status;
      error.retryable = status >= 500;
      return error;
    }
  }

  global.MockAnalyticsApi = MockAnalyticsApi;
})(window);
