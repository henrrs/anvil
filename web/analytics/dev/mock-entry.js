(function installMockWorkspace(global) {
  const allowed = ["healthy", "home-populated", "table-remote", "table-local", "query-results", "ask-anvil", "active-operation",
    "offline", "degraded", "materializing", "large-catalog", "single-warehouse", "no-warehouses", "warehouse-disappeared",
    "legacy-migrating", "local-needs-update", "parallel-materializations", "queued-materialization", "half-progress",
    "network-retry", "resumable-transfer", "identity-degraded", "persistent-chat", "failed-operations", "many-local", "many-recent"];
  const requested = new URLSearchParams(global.location.search).get("scenario") || "healthy";
  const scenario = allowed.includes(requested) ? requested : "healthy";
  const firstLoad = sessionStorage.getItem("anvil:analytics:mock-scenario") !== scenario;
  if (firstLoad) {
    for (const key of ["anvil:analytics:recent-tables:v1", "anvil:analytics:favorites:v1", "anvil:analytics:layout:v1"])
      localStorage.removeItem(key);
    sessionStorage.setItem("anvil:analytics:mock-scenario", scenario);
  }
  if (firstLoad && ["home-populated", "table-remote", "table-local", "query-results", "ask-anvil", "many-recent"].includes(scenario)) {
    localStorage.setItem("anvil:analytics:recent-tables:v1", JSON.stringify(scenario === "many-recent"
      ? ["main.finance.transactions", "main.finance.payment_events", "main.finance.customer_accounts",
        "main.operations.fulfillment_events", "main.operations.inventory_position"]
      : ["main.finance.transactions", "main.finance.daily_revenue"]));
    localStorage.setItem("anvil:analytics:favorites:v1", JSON.stringify(["main.finance.payment_events"]));
  }
  global.anvilAnalyticsApi = new global.MockAnalyticsApi(scenario);
  global.addEventListener("DOMContentLoaded", () => {
    const target = document.querySelector(".topbar-right");
    if (!target) return;
    const badge = document.createElement("span");
    badge.className = "mock-badge";
    badge.textContent = `MOCK · ${scenario}`;
    target.prepend(badge);
  });
  global.anvilAnalyticsVisualSetup = async () => {
    const options = new URLSearchParams(global.location.search);
    if (scenario === "table-remote") await global.openTable("main.finance.daily_revenue");
    if (scenario === "table-local" || scenario === "ask-anvil") await global.openTable("main.finance.transactions");
    if (scenario === "query-results") {
      global.createQuery("SELECT status, count(*) AS transactions FROM main.finance.transactions GROUP BY status", "Transactions by status");
      await global.runQuery();
    }
    if (scenario === "ask-anvil") {
      global.addChatMessage("user", "Summarize this table and its local coverage.");
      global.addChatMessage("assistant", "Transactions contains one row per posted financial transaction. Six columns are available in the catalog, and a complete local snapshot is ready for covered read-only queries.");
    }
    const filter = options.get("filter");
    if (["all", "favorites", "local"].includes(filter)) document.querySelector(`[data-catalog-filter="${filter}"]`)?.click();
    if (options.get("health") === "open") document.getElementById("health-menu").open = true;
    if (options.get("collapse") === "catalog") document.getElementById("collapse-catalog").click();
    if (options.get("collapse") === "assistant") document.getElementById("collapse-assistant").click();
    if (options.get("tabs") === "many") {
      for (let index = 0; index < 9; index += 1) global.createQuery(`SELECT ${index} AS sample`, `Query ${index + 1}`);
    }
    if (options.get("expand") === "first") {
      const first = document.querySelector("#catalog-tree .tree-group");
      if (first) first.open = true;
      await new Promise((resolve) => global.setTimeout(resolve, 100));
      const nested = first?.querySelector(".tree-group");
      if (nested) nested.open = true;
      await new Promise((resolve) => global.setTimeout(resolve, 100));
    }
    document.documentElement.dataset.mockReady = "true";
  };
})(window);
