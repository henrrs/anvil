const $ = (id) => document.getElementById(id);
const apiClient = window.anvilAnalyticsApi || new window.HttpAnalyticsApi();
const WAREHOUSE_KEY = "anvil:analytics:selected-warehouse:v1";
const FAVORITES_KEY = "anvil:analytics:favorites:v1";
const RECENTS_KEY = "anvil:analytics:recent-tables:v1";
const LAYOUT_KEY = "anvil:analytics:layout:v1";
const QUERY_SPLIT_KEY = "analytics.query.splitRatio";
const PAGE_SIZE = 100;

function readStorage(key, fallback) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "null");
    return value ?? fallback;
  } catch { return fallback; }
}

function writeStorage(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* browser storage is optional */ }
}

const storedFavorites = readStorage(FAVORITES_KEY, []);
const state = {
  profile: null,
  runtime: null,
  databricks: null,
  local: null,
  warehouses: [],
  warehouseStatus: "LOADING",
  selectedWarehouse: typeof readStorage(WAREHOUSE_KEY, "") === "string" ? readStorage(WAREHOUSE_KEY, "") : "",
  warehouseMessage: "",
  warehouseInvalidated: false,
  catalogItems: [],
  catalogStatus: "EMPTY",
  catalogOffset: 0,
  catalogHasMore: false,
  catalogSearchTerm: "",
  catalogFilter: "all",
  catalogSearchResults: [],
  catalogKnown: new Map(),
  localStates: new Map(),
  favorites: new Set(Array.isArray(storedFavorites) ? storedFavorites.filter((item) => typeof item === "string") : []),
  recentTables: Array.isArray(readStorage(RECENTS_KEY, [])) ? readStorage(RECENTS_KEY, []).filter((item) => typeof item === "string").slice(0, 8) : [],
  workspaces: [],
  activeWorkspaceId: "home",
  nextQueryNumber: 1,
  queryHistory: [],
  datasets: [],
  operations: [],
  investigations: [],
  catalogSyncedAt: null,
  layout: readStorage(LAYOUT_KEY, {}),
  chatBusy: false,
  chatNextBefore: null,
};

function node(tag, className = "", value = undefined) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (value !== undefined) element.textContent = String(value);
  return element;
}

function icon(kind) {
  const paths = {
    CATALOG: "M3 5h18v14H3z M3 10h18",
    SCHEMA: "M4 4h16v16H4z M4 9h16 M9 9v11",
    VIEW: "M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
    TABLE: "M3 4h18v16H3z M3 10h18 M9 10v10 M15 10v10",
    STAR: "m12 2 3.1 6.3 7 1-5.05 4.9 1.2 6.9L12 17.8l-6.25 3.3 1.2-6.9L1.9 9.3l7-1z",
    CLOSE: "M6 6l12 12M18 6 6 18",
    TRASH: "M4 7h16M10 11v6M14 11v6M5 7l1 14h12l1-14M9 7V4h6v3",
  };
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", kind === "STAR_FILLED" ? "currentColor" : "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.7");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", paths[kind === "STAR_FILLED" ? "STAR" : kind] || paths.TABLE);
  svg.append(path);
  return svg;
}

function button(label, className, action, title = "") {
  const element = node("button", className, label);
  element.type = "button";
  if (title) element.title = title;
  element.addEventListener("click", action);
  return element;
}

function safeText(value, fallback = "Not available") {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function formatBytes(value) {
  let bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KiB", "MiB", "GiB", "TiB"];
  let index = -1;
  do { bytes /= 1024; index += 1; } while (bytes >= 1024 && index < units.length - 1);
  return `${bytes.toFixed(bytes >= 10 ? 0 : 1)} ${units[index]}`;
}

function relativeTime(value) {
  if (!value) return "";
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "";
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `${hours}h ago` : `${Math.floor(hours / 24)}d ago`;
}

function setStatus(id, value, detail = "") {
  const item = $(id);
  if (!item) return;
  const dot = item.querySelector(".status-dot");
  const label = item.querySelector("b");
  const normalized = String(value || "UNKNOWN").toUpperCase();
  if (label) label.textContent = normalized.replaceAll("_", " ");
  if (dot) {
    dot.classList.toggle("ready", ["READY", "ONLINE", "CONNECTED"].includes(normalized));
    dot.classList.toggle("warn", ["DEGRADED", "STALE", "BUSY", "STARTING", "CONFIGURED"].includes(normalized));
    dot.classList.toggle("failed", ["OFFLINE", "FAILED", "UNAVAILABLE"].includes(normalized));
  }
  if (detail) item.title = detail;
  const values = ["status-anvil", "status-opencode", "status-databricks", "status-duckdb"]
    .map((key) => $(key)?.querySelector("b")?.textContent || "UNKNOWN");
  const summary = $("health-summary-label");
  const summaryDot = $("health-summary-dot");
  if (summary && summaryDot) {
    const allReady = values.every((entry) => entry === "READY");
    const pending = values.some((entry) => entry === "UNKNOWN");
    summary.textContent = allReady ? "Systems healthy" : pending ? "Checking systems" : "Systems need attention";
    summaryDot.classList.toggle("ready", allReady);
    summaryDot.classList.toggle("warn", !allReady && !pending);
  }
}

async function api(path, options = {}) {
  return apiClient.request(path, options);
}

function post(path, body = {}) {
  return api(path, { method: "POST", body: JSON.stringify(body) });
}

function resizeChatComposer() {
  const input = $("chat-input");
  if (!input) return;
  input.style.height = "auto";
  input.style.height = `${Math.min(224, Math.max(input.scrollHeight, 80))}px`;
  input.style.overflowY = input.scrollHeight > 224 ? "auto" : "hidden";
}

function toast(message, kind = "info") {
  const region = $("toast-region");
  const item = node("div", `toast ${kind}`, message);
  region.append(item);
  window.setTimeout(() => item.remove(), 5000);
}

function tableName(value) {
  return String(value || "").split(".").at(-1) || String(value || "Unknown table");
}

function queryWorkspace(id = state.activeWorkspaceId) {
  return state.workspaces.find((workspace) => workspace.id === id) || null;
}

function activeTableWorkspace() {
  const current = queryWorkspace();
  return current?.kind === "table" ? current : null;
}

function activeQueryWorkspace() {
  const current = queryWorkspace();
  return current?.kind === "query" ? current : null;
}

function renderWorkspaceTabs() {
  const container = $("workspace-tabs");
  container.replaceChildren();
  const homeWrap = node("div", `workspace-tab-wrap ${state.activeWorkspaceId === "home" ? "active" : ""}`);
  const home = button("", `workspace-tab ${state.activeWorkspaceId === "home" ? "active" : ""}`,
    () => switchWorkspace("home"), "Analytics home");
  home.setAttribute("role", "tab");
  home.setAttribute("aria-selected", String(state.activeWorkspaceId === "home"));
  const homeContent = node("span", "workspace-tab-content");
  homeContent.append(node("span", "home-tab-icon", "⌂"), node("span", "workspace-tab-label", "Home"));
  home.append(homeContent);
  homeWrap.append(home);
  container.append(homeWrap);
  for (const workspace of state.workspaces) {
    const wrap = node("div", `workspace-tab-wrap ${state.activeWorkspaceId === workspace.id ? "active" : ""}`);
    const tab = button("", `workspace-tab ${state.activeWorkspaceId === workspace.id ? "active" : ""}`,
      () => switchWorkspace(workspace.id), workspace.title);
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", String(state.activeWorkspaceId === workspace.id));
    const content = node("span", "workspace-tab-content");
    content.append(node("span", "workspace-kind-icon", workspace.kind === "table" ? "▤" : "⌘"),
      node("span", "workspace-tab-label", workspace.title));
    tab.append(content);
    const close = button("", "workspace-tab-close", (event) => closeWorkspace(workspace.id, event), `Close ${workspace.title}`);
    close.setAttribute("aria-label", `Close ${workspace.title}`);
    close.append(icon("CLOSE"));
    wrap.append(tab, close);
    container.append(wrap);
  }
  const activeTab = container.querySelector(".workspace-tab.active");
  if (activeTab) {
    const viewport = container.getBoundingClientRect();
    const active = activeTab.getBoundingClientRect();
    if (active.left < viewport.left) container.scrollLeft -= viewport.left - active.left;
    else if (active.right > viewport.right) container.scrollLeft += active.right - viewport.right;
  }
}

function switchWorkspace(id) {
  state.activeWorkspaceId = id;
  renderWorkspaceTabs();
  renderActiveWorkspace();
  updateAskContext();
}

function closeWorkspace(id, event) {
  event?.stopPropagation();
  const index = state.workspaces.findIndex((workspace) => workspace.id === id);
  if (index < 0) return;
  state.workspaces.splice(index, 1);
  if (state.activeWorkspaceId === id) {
    const next = state.workspaces[index] || state.workspaces[index - 1];
    state.activeWorkspaceId = next?.id || "home";
  }
  renderWorkspaceTabs();
  renderActiveWorkspace();
  updateAskContext();
}

function switchPage(page) {
  state.activeWorkspaceId = page;
  renderWorkspaceTabs();
  renderActiveWorkspace();
  updateAskContext();
}

function renderActiveWorkspace() {
  const id = state.activeWorkspaceId;
  $("analytics-home").classList.toggle("hidden", id !== "home");
  $("table-workspace").classList.toggle("hidden", !id.startsWith("table:"));
  $("query-workspace").classList.toggle("hidden", !id.startsWith("query:"));
  if (id === "home") renderHome();
  else if (id.startsWith("table:")) renderTableWorkspace(queryWorkspace(id));
  else renderQueryWorkspace(queryWorkspace(id));
}

function quoteIdentifier(value) {
  return /^[A-Za-z_][A-Za-z0-9_$]*$/.test(value)
    ? `\`${value}\`` : `\`${String(value).replaceAll("`", "``")}\``;
}

function defaultSql(fullName = "") {
  if (!fullName) return "SELECT 1 AS ready_check\nLIMIT 10";
  const source = fullName.split(".").map(quoteIdentifier).join(".");
  return `SELECT *\nFROM ${source}\nLIMIT 100`;
}

function createQuery(sql = "", title = "") {
  const number = state.nextQueryNumber++;
  const workspace = { id: `query:${number}`, kind: "query", title: title || `Query ${number}`,
    sql: sql || defaultSql(activeTableWorkspace()?.fullName || ""), route: "AUTO", result: null,
    status: "idle", explain: null, message: "Read-only SQL. Results are capped for safety." };
  state.workspaces.push(workspace);
  switchWorkspace(workspace.id);
  return workspace;
}

async function openTable(fullName) {
  if (!fullName) return;
  let workspace = state.workspaces.find((item) => item.kind === "table" && item.fullName === fullName);
  if (!workspace) {
    workspace = { id: `table:${fullName}`, kind: "table", title: tableName(fullName),
      fullName, section: "overview", detail: null, coverage: null, preview: null, lineage: null, loading: true };
    state.workspaces.push(workspace);
  }
  state.recentTables = [fullName, ...state.recentTables.filter((item) => item !== fullName)].slice(0, 8);
  writeStorage(RECENTS_KEY, state.recentTables);
  switchWorkspace(workspace.id);
  setLocalState(fullName, "checking");
  try {
    const [detail, coverage] = await Promise.all([
      api(`/api/tables/${encodeURIComponent(fullName)}`),
      api(`/api/tables/${encodeURIComponent(fullName)}/coverage`),
    ]);
    workspace.detail = detail.object || null;
    workspace.coverage = coverage;
    workspace.loading = false;
    setLocalState(fullName, coverage.covered ? "full" : coverage.snapshot_id ? "partial" : "remote");
  } catch (error) {
    workspace.loading = false;
    workspace.error = error.message;
    setLocalState(fullName, "stale");
  }
  renderWorkspaceTabs();
  if (state.activeWorkspaceId === workspace.id) renderTableWorkspace(workspace);
  renderHome();
  updateAskContext();
}

function renderWorkspaceContext() {
  const table = activeTableWorkspace();
  const query = activeQueryWorkspace();
  if (table) return { title: table.fullName, source: "TABLE", detail: table.detail };
  if (query) return { title: query.title, source: "QUERY", detail: query };
  return { title: "No active object", source: "GENERAL", detail: null };
}

function renderTableWorkspace(workspace) {
  if (!workspace) return;
  $("table-title").textContent = workspace.fullName;
  $("table-breadcrumb").textContent = workspace.fullName.split(".").slice(0, -1).join(" / ").toUpperCase();
  $("table-comment").textContent = workspace.detail?.comment || "Table metadata from the local catalog cache.";
  const favorite = state.favorites.has(workspace.fullName);
  $("favorite-table").replaceChildren(icon(favorite ? "STAR_FILLED" : "STAR"));
  $("favorite-table").classList.toggle("favorite-button", true);
  $("favorite-table").classList.toggle("active", favorite);
  $("favorite-table").title = favorite ? "Remove from favorites" : "Add to favorites";
  $("favorite-table").setAttribute("aria-label", $("favorite-table").title);
  $("favorite-table").setAttribute("aria-pressed", String(favorite));
  const localAction = $("table-make-local");
  const freshness = String(workspace.coverage?.freshness || "UNKNOWN").toUpperCase();
  const isCurrent = Boolean(workspace.coverage?.covered) && freshness === "CURRENT";
  localAction.disabled = Boolean(workspace.activeOperation);
  localAction.textContent = workspace.activeOperation ? "Updating…" : isCurrent ? "Local ✓"
    : workspace.coverage?.snapshot_id ? "Update local copy" : "Keep local";
  localAction.title = workspace.activeOperation ? "A local copy is being updated"
    : isCurrent ? "This table has a verified current local copy" : "Reuse or create this table's local copy";
  localAction.setAttribute("aria-label", localAction.textContent);
  document.querySelectorAll(".table-tab").forEach((tab) => {
    const active = tab.dataset.section === workspace.section;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  const content = $("table-section-content");
  content.replaceChildren();
  if (workspace.loading) {
    content.append(node("div", "empty-state", "Loading table metadata…"));
    return;
  }
  if (workspace.error) {
    content.append(node("div", "error-card", workspace.error));
    return;
  }
  const object = workspace.detail || {};
  const columns = Array.isArray(object.columns) ? object.columns : [];
  if (workspace.section === "overview") {
    renderTableOverview(content, object, workspace.coverage, columns);
  } else if (workspace.section === "columns") {
    renderColumns(content, columns);
  } else if (workspace.section === "preview") {
    renderTablePreview(content, workspace);
  } else if (workspace.section === "lineage") {
    renderTableLineage(content, workspace);
  } else {
    renderLocalData(content, workspace);
  }
}

function renderTableOverview(target, object, coverage, columns) {
  const props = object.properties || {};
  const summary = node("section", "table-summary");
  const type = props.table_type || object.object_type || "Object";
  const format = props.data_source_format || "";
  summary.append(node("p", "table-summary-main", [type, format, `${columns.length} columns`].filter(Boolean).join(" · ")));
  const details = [props.owner ? `Owner: ${props.owner}` : "", object.updated_at ? `Modified ${relativeTime(object.updated_at)}` : ""].filter(Boolean);
  if (details.length) summary.append(node("p", "table-summary-meta", details.join("  ·  ")));
  const localStatus = coverage?.covered && coverage?.freshness === "CURRENT" ? "Local copy is current"
    : coverage?.snapshot_id ? "Local copy available; freshness " + String(coverage.freshness || "unknown").toLowerCase().replaceAll("_", " ")
      : "Remote only";
  summary.append(node("p", "table-local-state " + (coverage?.snapshot_id ? "available" : "remote"), localStatus));
  target.append(summary);
  if (object.comment) {
    target.append(node("h2", "section-title", "Description"), node("p", "subtle-copy", object.comment));
  }
  if (object.properties?.partition_columns?.length) {
    target.append(node("h2", "section-title", "Partitioning"), node("p", "subtle-copy", object.properties.partition_columns.join(", ")));
  }
}

function fact(label, value) {
  const cell = node("div", "fact-card");
  cell.append(node("span", "", label), node("strong", "", value || "Not available"));
  return cell;
}

function renderColumns(target, columns) {
  if (!columns.length) {
    target.append(node("div", "empty-state", "Column metadata is not cached yet. Refresh table metadata when Databricks is available."));
    return;
  }
  const list = node("div", "column-list");
  for (const column of columns.slice(0, 500)) {
    const row = node("div", "column-row");
    row.append(node("strong", "", column.name || "Unnamed column"),
      node("small", "", column.type_text || column.type_name || "UNKNOWN"));
    if (column.comment) row.append(node("span", "column-comment", column.comment));
    list.append(row);
  }
  target.append(list);
  if (columns.length > 500) target.append(node("p", "subtle-copy", `Showing 500 of ${columns.length} columns.`));
}

function renderTablePreview(target, workspace) {
  if (!workspace.preview) {
    const copy = node("div", "empty-state compact", "Preview rows are fetched only when you ask.");
    const preview = button("Preview rows", "button secondary", () => loadTablePreview(workspace));
    target.append(copy, preview);
    return;
  }
  if (workspace.preview.error) {
    target.append(node("div", "error-card", workspace.preview.error));
    return;
  }
  renderResults(target, workspace.preview);
}

async function loadTablePreview(workspace) {
  if (!state.selectedWarehouse) return showWarehouseRequired("Select a SQL Warehouse to preview remote rows.");
  workspace.preview = { loading: true };
  renderTableWorkspace(workspace);
  try {
    workspace.preview = await api(`/api/tables/${encodeURIComponent(workspace.fullName)}/preview?warehouse_id=${encodeURIComponent(state.selectedWarehouse)}&limit=20`);
    if (workspace.preview.status !== "READY" && workspace.preview.error) {
      workspace.preview = { error: "Preview is unavailable for the selected SQL Warehouse." };
    }
  } catch {
    workspace.preview = { error: "Preview is unavailable. Check the selected SQL Warehouse and try again." };
  }
  renderTableWorkspace(workspace);
}

function renderTableLineage(target, workspace) {
  if (!workspace.lineage) {
    target.append(node("div", "empty-state compact", "Lineage is requested from Databricks when you open this section."),
      button("Load lineage", "button secondary", () => loadTableLineage(workspace)));
    return;
  }
  if (workspace.lineage.error) {
    target.append(node("div", "error-card", workspace.lineage.error));
    return;
  }
  const rows = workspace.lineage.rows || [];
  if (!rows.length) {
    target.append(node("div", "empty-state", "No lineage events were returned for this table."));
    return;
  }
  const list = node("div", "lineage-list");
  for (const row of rows.slice(0, 100)) list.append(node("div", "lineage-row",
    `${row.event_time || "Unknown time"} · ${row.source_table_full_name || "Unknown source"} → ${row.target_table_full_name || "Unknown target"}`));
  target.append(list);
}

async function loadTableLineage(workspace) {
  if (!state.selectedWarehouse) return showWarehouseRequired("Select a SQL Warehouse to load lineage.");
  workspace.lineage = { loading: true };
  renderTableWorkspace(workspace);
  try {
    workspace.lineage = await api(`/api/tables/${encodeURIComponent(workspace.fullName)}/lineage?warehouse_id=${encodeURIComponent(state.selectedWarehouse)}&limit=50`);
  } catch {
    workspace.lineage = { error: "Lineage is unavailable. Check workspace permissions and the selected SQL Warehouse." };
  }
  renderTableWorkspace(workspace);
}

function renderLocalData(target, workspace) {
  const coverage = workspace.coverage;
  const covered = Boolean(coverage?.covered);
  const card = node("div", `coverage-card ${covered ? "covered" : ""}`);
  card.append(node("strong", "", covered ? "Local copy covers this table" : coverage?.snapshot_id ? "Local copy needs attention" : "No local copy"));
  card.append(node("p", "", coverage?.reason || (covered ? "The local Parquet copy is ready for queries within its coverage." : "Keep a local copy when you need local execution.")));
  const details = node("div", "table-facts");
  details.append(fact("Rows", coverage?.rows ? Number(coverage.rows).toLocaleString() : "Not available"),
    fact("Size", coverage?.bytes ? formatBytes(coverage.bytes) : "Not available"),
    fact("Columns", coverage?.columns_mode === "ALL" ? "All columns" : coverage?.columns?.join(", ") || "Not available"),
    fact("Rows included", !coverage?.snapshot_id ? "Not available" : coverage.rows_mode === "FILTERED" ? "Filtered rows" : "All rows"),
    fact("Updated", relativeTime(coverage?.updated_at) || "Not available"));
  const actions = node("div", "local-data-actions");
  if (coverage?.dataset_id) actions.append(button("Remove local copy", "button secondary danger-text",
    () => removeLocalDataset({ dataset_id: coverage.dataset_id, source_name: workspace.fullName }),
    "Remove local copy of " + workspace.fullName));
  target.append(card, node("h2", "section-title", "Coverage"), details, actions);
}

function renderQueryWorkspace(workspace) {
  if (!workspace) return;
  $("query-title").textContent = workspace.title;
  $("query-file-name").textContent = `${workspace.title.toLowerCase().replaceAll(" ", "-")}.sql`;
  $("sql-editor").value = workspace.sql;
  $("query-route").value = workspace.route;
  renderWarehouseSelector();
  setQueryStatus(workspace.status, workspace.status === "idle" ? "READY" : workspace.status.toUpperCase());
  $("route-badge").textContent = workspace.result?.route || workspace.route;
  $("query-message").textContent = workspace.message || "Read-only SQL. Results are capped for safety.";
  $("query-metrics").textContent = workspace.result
    ? String(workspace.result.row_count ?? workspace.result.rows?.length ?? 0) + " rows · " +
      formatBytes(workspace.result.byte_count || 0) +
      (workspace.result.latency_ms == null ? "" : " · " + workspace.result.latency_ms + " ms")
    : "";
  const results = $("query-results");
  results.replaceChildren();
  if (workspace.error) results.append(node("div", "error-card", workspace.error));
  else if (workspace.result) renderResults(results, workspace.result);
  else if (workspace.status === "running") {
    const progress = node("div", "query-progress");
    progress.setAttribute("role", "status");
    progress.setAttribute("aria-live", "polite");
    progress.append(node("span", "activity-spinner"), node("span", "", workspace.message || "Preparing query…"));
    results.append(progress);
  } else {
    const placeholder = node("div", "results-placeholder", "");
    placeholder.append(node("span", "", "⌁"), node("p", "", "Run a query to inspect results"));
    results.append(placeholder);
  }
}

function setQueryStatus(status, label = "") {
  const item = $("query-status-label");
  if (!item) return;
  item.className = `query-state ${status || "idle"}`;
  item.textContent = label || String(status || "idle").toUpperCase();
}

function renderResults(target, result) {
  target.replaceChildren();
  const columns = Array.isArray(result.columns) ? result.columns : [];
  const rows = Array.isArray(result.rows) ? result.rows : [];
  if (!columns.length) {
    target.append(node("div", "empty-state compact", result.status === "BROWSE_ONLY" ? "Preview is unavailable." : "No columns were returned."));
    return;
  }
  const scroll = node("div", "table-scroll");
  const table = node("table", "data-table");
  const head = node("thead");
  const heading = node("tr");
  for (const column of columns.slice(0, 100)) heading.append(node("th", "", column));
  head.append(heading);
  const body = node("tbody");
  for (const values of rows.slice(0, 100)) {
    const row = node("tr");
    for (const value of values.slice(0, 100)) row.append(node("td", "", value === null ? "NULL" : typeof value === "object" ? JSON.stringify(value) : value));
    body.append(row);
  }
  table.append(head, body);
  scroll.append(table);
  target.append(scroll);
  if (!rows.length) target.append(node("p", "subtle-copy", "No rows returned."));
  if (result.truncated) target.append(node("p", "subtle-copy", "Results were capped for safety."));
}

function setLocalState(fullName, value) {
  if (!fullName) return;
  state.localStates.set(fullName, value);
  const table = queryWorkspace(`table:${fullName}`);
  if (table) table.localState = value;
  if (state.catalogFilter === "local") renderCatalogView();
  else for (const row of $("catalog-tree").querySelectorAll(".tree-table-row")) {
    if (row.dataset.fullName === fullName) row.querySelector(".local-indicator")?.replaceWith(localIndicator(fullName));
  }
}

function localIndicator(fullName) {
  const value = state.localStates.get(fullName);
  if (!value || value === "remote") return node("span", "local-indicator absent");
  const indicator = node("span", `local-indicator ${value === "full" ? "full" : value === "partial" ? "partial" : value === "stale" ? "stale" : ""}`,
    value === "full" ? "●" : value === "partial" ? "◐" : value === "stale" ? "⚠" : value === "checking" ? "↻" : "·");
  indicator.title = value === "full" ? "Complete local snapshot" : value === "partial" ? "Partial local snapshot"
    : value === "stale" ? "Local state could not be checked" : value === "checking" ? "Checking local data" : "Local state not checked";
  return indicator;
}

function catalogObjectRow(item) {
  const kind = String(item.object_type || "TABLE").toUpperCase();
  const label = item.full_name?.split(".").at(-1) || item.name || "Unknown object";
  const row = node("div", "tree-table-row");
  row.dataset.fullName = item.full_name;
  const select = button("", `tree-item ${queryWorkspace()?.fullName === item.full_name ? "active" : ""}`,
    () => openTable(item.full_name), item.comment || item.full_name);
  const glyph = node("span", `tree-icon ${kind.toLowerCase()}`);
  glyph.append(icon(kind));
  select.append(glyph, node("span", "tree-name", label), localIndicator(item.full_name));
  const favorite = state.favorites.has(item.full_name);
  const star = button("", `tree-star ${favorite ? "active" : ""}`, () => toggleFavorite(item.full_name),
    favorite ? "Remove favorite" : "Add favorite");
  star.append(icon(favorite ? "STAR_FILLED" : "STAR"));
  star.setAttribute("aria-label", `${favorite ? "Remove" : "Add"} ${label} ${favorite ? "from" : "to"} favorites`);
  star.setAttribute("aria-pressed", String(favorite));
  row.append(select, star);
  return row;
}

function renderTree(items, container, depth = 0, response = null) {
  container.replaceChildren();
  if (!items.length) {
    const status = response?.status || "NOT_LOADED";
    const error = response?.error;
    const message = status === "NOT_LOADED" || status === "PENDING" || status === "LOADING"
      ? "Loading objects…"
      : status === "BROWSE_ONLY" && error === "PERMISSION_DENIED"
        ? "Permission denied while loading catalog metadata."
        : status === "BROWSE_ONLY" || status === "FAILED"
          ? "Catalog metadata could not be loaded. Retry when the provider is available."
          : "No catalog objects are available.";
    container.append(node("div", status === "LOADING" || status === "PENDING" ? "tree-loading" : "tree-empty", message));
    return;
  }
  const fragment = document.createDocumentFragment();
  for (const item of items) {
    if (item.full_name) state.catalogKnown.set(item.full_name, item);
    const kind = String(item.object_type || "TABLE").toUpperCase();
    const label = item.full_name?.split(".").at(-1) || item.name || item.full_name || "Unknown object";
    if (kind === "CATALOG" || kind === "SCHEMA") {
      const disclosure = node("details", "tree-group");
      const summary = node("summary");
      const glyph = node("span", `tree-icon ${kind.toLowerCase()}`);
      glyph.append(icon(kind));
      summary.append(node("span", "tree-chevron", "›"), glyph, node("span", "tree-name", label));
      disclosure.append(summary);
      const children = node("div", "tree-children");
      disclosure.append(children);
      let loaded = false;
      disclosure.addEventListener("toggle", async () => {
        if (!disclosure.open || loaded) return;
        loaded = true;
        await loadCatalogChildren(item, children, depth + 1);
      });
      fragment.append(disclosure);
    } else {
      fragment.append(catalogObjectRow(item));
    }
  }
  container.append(fragment);
}

function renderCatalogView() {
  const tree = $("catalog-tree");
  const term = state.catalogSearchTerm;
  const filter = state.catalogFilter;
  let items = term ? state.catalogSearchResults : state.catalogItems;
  if (filter === "favorites") items = [...state.favorites].map((name) => state.catalogKnown.get(name) || { full_name: name, object_type: "TABLE" });
  if (filter === "local") {
    const names = new Set(state.datasets.filter((item) => item.state === "READY").map((item) => item.source_name || item.payload?.plan?.source_name).filter(Boolean));
    for (const [name, value] of state.localStates) if (["full", "partial"].includes(value)) names.add(name);
    items = [...names].map((name) => state.catalogKnown.get(name) || { full_name: name, object_type: "TABLE" });
  }
  if (term && filter !== "all") items = items.filter((item) => `${item.full_name || ""} ${item.comment || ""}`.toLowerCase().includes(term.toLowerCase()));
  if (filter === "all" && !term) {
    renderTree(items, tree, 0, { status: state.catalogStatus });
    if (state.catalogHasMore) tree.append(button("Load 100 more catalogs", "tree-load-more", () => loadCatalog({ offset: state.catalogOffset, append: true })));
  } else {
    tree.replaceChildren();
    for (const item of items) tree.append(catalogObjectRow(item));
    if (!items.length) tree.append(node("div", "empty-state compact", filter === "favorites" ? "No favorites yet. Star an object in the catalog." : filter === "local" ? "No local datasets yet." : "No cached matches. Refine your search."));
  }
}

function catalogPageUrl(parent, offset) {
  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
  if (!parent) return `/api/catalog?${params}`;
  const [catalog, schema] = parent.split(".");
  return schema
    ? `/api/catalog/${encodeURIComponent(catalog)}/${encodeURIComponent(schema)}/tables?${params}`
    : `/api/catalog/${encodeURIComponent(catalog)}/schemas?${params}`;
}

async function loadCatalogChildren(item, container, depth, offset = 0, append = false) {
  if (!append) container.replaceChildren(node("div", "tree-loading", "Loading objects…"));
  try {
    const result = await api(catalogPageUrl(item.full_name, offset));
    const rows = result.items || [];
    if (!append) container.replaceChildren();
    const entries = node("div", "tree-page");
    renderTree(rows, entries, depth, result);
    container.append(entries);
    if (result.has_more) {
      const more = button("Load 100 more", "tree-load-more", async () => {
        more.disabled = true;
        more.textContent = "Loading…";
        await loadCatalogChildren(item, container, depth, result.next_offset, true);
      });
      more.dataset.offset = String(result.next_offset);
      container.append(more);
    }
    if (result.status === "BROWSE_ONLY") setCatalogMessage("Cached metadata · provider unavailable", "BROWSE ONLY");
  } catch (error) {
    if (!append) container.replaceChildren();
    container.append(node("div", "tree-empty", error.message));
  }
}

function setCatalogMessage(message, status = "LOCAL CACHE") {
  $("catalog-state").textContent = status;
  $("catalog-state").title = message;
  $("catalog-led").classList.toggle("warn", status === "BROWSE ONLY" || status === "STALE");
  $("catalog-led").classList.toggle("failed", status === "FAILED");
}

async function loadCatalog({ refresh = false, append = false, offset = 0 } = {}) {
  const tree = $("catalog-tree");
  if (!refresh && !append && !state.catalogItems.length) tree.replaceChildren(node("div", "empty-state compact", "Loading catalog…"));
  try {
    let result;
    if (refresh) result = await post("/api/catalog/refresh", { scope: "catalogs", limit: PAGE_SIZE, offset: 0 });
    else result = await api(`/api/catalog?limit=${PAGE_SIZE}&offset=${offset}`);
    const items = result.items || [];
    state.catalogItems = append ? [...state.catalogItems, ...items] : items;
    state.catalogStatus = result.status || "EMPTY";
    state.catalogOffset = result.next_offset || state.catalogItems.length;
    state.catalogHasMore = Boolean(result.has_more);
    if (refresh && result.status === "READY") state.catalogSyncedAt = new Date().toISOString();
    renderCatalogView();
    const count = state.catalogItems.length;
    $("catalog-count").textContent = `${count.toLocaleString()} cached catalog${count === 1 ? "" : "s"}`;
    $("catalog-freshness").textContent = state.catalogSyncedAt ? `Synced ${relativeTime(state.catalogSyncedAt)}`
      : count ? "Cached catalog" : "Catalog not synced";
    setCatalogMessage(result.error || (count ? "Catalog metadata available" : "No catalog cache yet"),
      result.status === "BROWSE_ONLY" ? "BROWSE ONLY" : result.status || "LOCAL CACHE");
    if (!count && !refresh && !state.catalogSearchTerm) {
      // A first local view may have no cache; attempt one safe metadata refresh.
      await loadCatalog({ refresh: true });
    }
    renderHome();
  } catch (error) {
    if (!append) tree.replaceChildren(node("div", "empty-state compact", error.message));
    setCatalogMessage(error.message, "FAILED");
  }
}

async function searchCatalog(value) {
  const term = value.trim();
  state.catalogSearchTerm = term;
  if (state.catalogFilter !== "all") { renderCatalogView(); return; }
  if (!term) { renderCatalogView(); return; }
  try {
    const result = await api(`/api/catalog/search?q=${encodeURIComponent(term)}&limit=${PAGE_SIZE}`);
    state.catalogSearchResults = result.items || [];
    for (const item of state.catalogSearchResults) if (item.full_name) state.catalogKnown.set(item.full_name, item);
    renderCatalogView();
    if (result.truncated) $("catalog-tree").append(node("div", "tree-empty", "Showing the first 100 matches. Refine your search to narrow the list."));
    setCatalogMessage("Search uses cached metadata", "LOCAL SEARCH");
  } catch (error) { setCatalogMessage(error.message, "SEARCH FAILED"); }
}

function toggleFavorite(fullName) {
  if (!fullName) return;
  if (state.favorites.has(fullName)) state.favorites.delete(fullName);
  else state.favorites.add(fullName);
  writeStorage(FAVORITES_KEY, [...state.favorites].slice(0, 200));
  if (state.catalogFilter === "favorites") renderCatalogView();
  else for (const row of $("catalog-tree").querySelectorAll(".tree-table-row")) {
    if (row.dataset.fullName !== fullName) continue;
    const star = row.querySelector(".tree-star");
    const favorite = state.favorites.has(fullName);
    star.replaceChildren(icon(favorite ? "STAR_FILLED" : "STAR"));
    star.classList.toggle("active", favorite);
    star.setAttribute("aria-pressed", String(favorite));
    star.setAttribute("aria-label", `${favorite ? "Remove" : "Add"} ${tableName(fullName)} ${favorite ? "from" : "to"} favorites`);
    star.title = favorite ? "Remove favorite" : "Add favorite";
  }
  renderHome();
  const workspace = queryWorkspace(`table:${fullName}`);
  if (workspace && state.activeWorkspaceId === workspace.id) renderTableWorkspace(workspace);
  if (state.catalogSearchTerm) searchCatalog($("catalog-search").value);
}

function renderHomeList(container, items, onClick = null) {
  container.replaceChildren();
  for (const item of items.slice(0, 5)) {
    const row = item.actionLabel ? node("div", "home-row static")
      : onClick ? button("", "home-row", () => onClick(item), item.title || "Open item") : node("div", "home-row static");
    row.append(node("span", "home-row-icon", item.icon || "•"));
    const copy = node("span", "home-row-copy");
    copy.append(node("strong", "", item.title || item.name || "Analytics item"), node("small", "", item.subtitle || ""));
    row.append(copy);
    if (item.updated_at) copy.append(node("small", "local-updated", "Updated " + relativeTime(item.updated_at)));
    if (item.state) row.append(node("span", `operation-pill ${String(item.state).toLowerCase()}`, item.state));
    if (item.actionLabel) row.append(button(item.actionLabel, "text-button", () => onClick?.(item), item.actionLabel + " " + (item.title || "operation")));
    container.append(row);
  }
}

function renderOperationCards(items) {
  const container = $("home-operations");
  container.replaceChildren();
  for (const operation of items) {
    const failed = operation.state === "FAILED";
    const row = node("article", `operation-row ${failed ? "needs-attention" : ""}`);
    const heading = node("div", "operation-heading");
    heading.append(node("strong", "", operation.source_name || "Local data"),
      node("span", `operation-pill ${String(operation.state).toLowerCase()}`,
        failed ? "Needs attention" : operation.state === "QUEUED" ? "Queued" : "In progress"));
    row.append(heading);
    row.append(node("div", "operation-detail", failed
      ? (operation.failure_reason === "TRANSFER_ERROR" ? "Download interrupted. Network connection was interrupted." :
        `Local copy interrupted · ${operation.failure_reason || operation.error_code || "Retry available"}`)
      : materializationPhaseText(operation.phase || operation.state)));
    const percent = Number.isFinite(operation.percent) ? Math.min(100, Math.max(0, Number(operation.percent))) : null;
    if (operation.state !== "QUEUED" && (percent !== null || !failed)) {
      const progress = node("div", `operation-progress ${percent === null ? "indeterminate" : ""}`);
      progress.setAttribute("role", "progressbar");
      progress.setAttribute("aria-label", `Download progress for ${operation.source_name || "local data"}`);
      if (percent !== null) progress.setAttribute("aria-valuenow", String(percent));
      progress.setAttribute("aria-valuemin", "0");
      progress.setAttribute("aria-valuemax", "100");
      progress.append(node("span"));
      if (percent !== null) progress.firstChild.style.width = `${percent}%`;
      row.append(progress);
    }
    const completed = Number(operation.completed_rows || operation.rows || 0);
    const planned = Number(operation.planned_rows || 0);
    const details = [
      percent !== null ? `${percent.toFixed(1)}%` : "",
      planned > 0 ? `${completed.toLocaleString()} / ${planned.toLocaleString()} rows` :
        completed > 0 ? `${completed.toLocaleString()} rows` : "",
      Number(operation.completed_chunks || 0) > 0 ? `${operation.completed_chunks} chunks` : "",
      Number(operation.completed_bytes || operation.bytes || 0) > 0 ? formatBytes(operation.completed_bytes || operation.bytes) : "",
      operation.started_at ? `Started ${relativeTime(operation.started_at)}` : "",
    ].filter(Boolean).join(" · ");
    if (details) row.append(node("div", "operation-detail", details));
    const actions = node("div", "operation-actions");
    if (failed) actions.append(button(operation.resume_available ? "Resume" : "Retry", "text-button",
      () => retryMaterialization(operation.operation_id, Boolean(operation.resume_available))));
    else if (["QUEUED", "PLANNED", "RUNNING", "PAUSED", "VALIDATING"].includes(operation.state))
      actions.append(button("Cancel", "text-button", async () => {
        try { await post(`/api/materializations/${encodeURIComponent(operation.operation_id)}/cancel`); await loadHomeData(); }
        catch (error) { toast(error.message, "error"); }
      }));
    row.append(actions);
    container.append(row);
  }
}

function renderHome() {
  const givenName = state.profile?.name?.split(/[\s@]/)[0] || "there";
  $("greeting-name").textContent = givenName;
  $("home-recent-count").textContent = String(state.recentTables.length);
  renderHomeList($("home-recent-tables"), state.recentTables.map((name) => ({ title: tableName(name), subtitle: name, icon: "▤" })),
    (item) => openTable(item.subtitle));
  $("home-favorite-count").textContent = String(state.favorites.size);
  renderHomeList($("home-favorites"), [...state.favorites].map((name) => ({ title: tableName(name), subtitle: name, icon: "★" })),
    (item) => openTable(item.subtitle));
  const queries = state.queryHistory.slice(0, 5).map((item) => ({
    title: String(item.sql || item.sql_text || "Query").replace(/\s+/g, " ").slice(0, 52),
    subtitle: `${item.route || "AUTO"} · ${item.status || "saved"}`,
    sql: item.sql || item.sql_text, icon: "⌘",
  }));
  renderHomeList($("home-recent-queries"), queries,
    (item) => createQuery(item.sql || "", "Recent query"));
  const readyDatasets = state.datasets.filter((item) => item.state === "READY");
  $("home-dataset-count").textContent = String(state.datasets.length);
  $("home-dataset-size").textContent = formatBytes(readyDatasets.reduce((sum, item) => sum + Number(item.bytes || 0), 0));
  renderLocalDatasets(state.datasets.slice(0, 5));
  const activeOps = state.operations.filter((item) => ["QUEUED", "PLANNED", "RUNNING", "PAUSED", "VALIDATING"].includes(item.state));
  const visibleOps = [...activeOps, ...state.operations.filter((item) => ["FAILED", "CANCELLED"].includes(item.state)).slice(0, 3)];
  $("home-operation-count").textContent = String(activeOps.length);
  renderOperationCards(visibleOps);
  $("home-investigation-count").textContent = String(state.investigations.length);
  renderHomeList($("home-investigations"), state.investigations.map((item) => ({
    title: item.subject || item.title || "Analytics investigation",
    subtitle: String(item.summary || item.content || "").slice(0, 82), icon: "✳",
  })));
  const completed = state.operations.filter((item) => item.state === "READY").slice(0, 3);
  renderHomeList($("home-completed-operations"), completed.map((item) => ({
    title: tableName(item.source_name || "Local copy"),
    subtitle: `Local copy completed ${relativeTime(item.updated_at)}`, icon: "✓",
  })));
  $("home-recent-tables-group").classList.toggle("hidden", !state.recentTables.length);
  $("home-recent-queries-group").classList.toggle("hidden", !queries.length);
  $("home-investigations-group").classList.toggle("hidden", !state.investigations.length);
  $("home-continue-empty").classList.toggle("hidden", Boolean(state.recentTables.length || queries.length));
  $("home-pinned-section").classList.toggle("hidden", !state.favorites.size);
  $("home-local-section").classList.toggle("hidden", !state.datasets.length);
  $("home-activity-section").classList.toggle("hidden", !state.investigations.length && !completed.length);
  $("home-operations-section").classList.toggle("hidden", !visibleOps.length);
}

function renderLocalDatasets(items) {
  const container = $("home-local-datasets");
  container.replaceChildren();
  for (const item of items) {
    const sourceName = item.source_name || "Local dataset";
    const row = node("div", "home-row static local-dataset-row");
    row.append(node("span", "home-row-icon", "●"));
    const copy = node("span", "home-row-copy");
    const columnCount = Array.isArray(item.columns) ? item.columns.length : (item.columns_mode === "ALL" ? "all" : 0);
    const detail = item.state === "READY"
      ? `${Number(item.rows || 0).toLocaleString()} rows · ${columnCount} columns · ${formatBytes(item.bytes || 0)}`
      : "Local copy needs update";
    copy.append(node("strong", "", tableName(sourceName)), node("small", "", detail));
    row.append(copy);
    row.append(button("Open", "text-button", () => openTable(sourceName), `Open ${sourceName}`));
    row.append(button("Remove", "text-button danger-text", () => removeLocalDataset(item), `Remove local copy of ${sourceName}`));
    container.append(row);
  }
}

async function removeLocalDataset(dataset) {
  const name = dataset.source_name || "this table";
  if (!window.confirm("Remove Anvil's local copy of " + name + "? The remote Databricks table will not be changed.")) return;
  try {
    await api("/api/datasets/" + encodeURIComponent(dataset.dataset_id), { method: "DELETE" });
    toast("Removed local copy of " + name + ".", "success");
    await loadHomeData();
    const workspace = queryWorkspace("table:" + name);
    if (workspace) await refreshCoverage(workspace);
  } catch (error) { toast(error.message, "error"); }
}

async function loadIdentity() {
  try {
    const me = await api("/api/me");
    state.profile = me;
    state.runtime = me.status?.runtime || {};
    state.databricks = me.status?.databricks || {};
    state.local = me.status?.local || {};
    const modelPolicy = me.status?.model_policy || {};
    const modelLabel = $("analytics-model-label");
    if (modelLabel) {
      const providerName = modelPolicy.provider_name || "GitHub Copilot";
      modelLabel.textContent = `${modelPolicy.display_name || "Luna 6"} · ${providerName}`;
      modelLabel.title = "Logical model: " + (modelPolicy.logical_model || "anvil-analytics") +
        "\nProvider: " + (modelPolicy.provider_name || modelPolicy.provider_preference || "GitHub Copilot") +
        "\nResolved model ID: " + (modelPolicy.model_id || "not yet validated") +
        "\nResolution: " + (modelPolicy.resolution || "NOT_CHECKED") +
        "\nFallback: " + (modelPolicy.fallback || "NONE");
      modelLabel.setAttribute("aria-label", modelLabel.textContent + ". Logical model " +
        (modelPolicy.logical_model || "anvil-analytics") + ". Provider " + providerName +
        ". Resolution " + (modelPolicy.resolution || "NOT_CHECKED") + ". Fallback " + (modelPolicy.fallback || "NONE"));
    }
    $("user-name").textContent = me.name || "Anvil user";
    $("user-avatar").textContent = (me.name || "A").trim().charAt(0).toUpperCase() || "A";
    $("workspace-label").textContent = me.workspace ? new URL(me.workspace).host : "Global workspace";
    const profileName = typeof me.profile === "string" ? me.profile : "";
    const environment = String(me.environment || profileName.split("-").at(-1) || "").toLowerCase();
    $("environment-name").textContent = ({ prod: "PROD", production: "PROD", dev: "DEV", development: "DEV",
      staging: "STAGING", stage: "STAGING", demo: "DEMO" })[environment] || "WORKSPACE";
    $("service-status").textContent = "ONLINE";
    $("connection-dot").classList.add("ready");
    $("storage-label").textContent = `${formatBytes(me.status?.local?.storage_bytes || 0)} local`;
    setStatus("status-anvil", "READY", "Analytics service is available");
    setStatus("status-opencode", me.status?.runtime?.status || "NOT_CONFIGURED", "OpenCode runtime");
    setStatus("status-databricks", me.status?.databricks?.status || "NOT_CONFIGURED", me.workspace || "Databricks identity");
    setStatus("status-duckdb", me.status?.local?.duckdb || "DEGRADED", "Local SQL engine");
    renderHome();
  } catch (error) {
    $("service-status").textContent = "OFFLINE";
    $("environment-name").textContent = "OFFLINE";
    $("workspace-label").textContent = "Analytics service unavailable";
    $("connection-dot").classList.add("failed");
    setStatus("status-anvil", "OFFLINE", error.message);
    toast(error.message, "error");
  }
}

function renderWarehouseSelector() {
  const select = $("warehouse-select");
  if (!select) return;
  select.replaceChildren();
  const available = [...state.warehouses].sort((left, right) =>
    Number(right.state === "RUNNING") - Number(left.state === "RUNNING"));
  if (state.warehouseStatus === "LOADING" && !available.length) {
    select.append(new Option("Loading warehouses…", ""));
    select.disabled = true;
    return;
  }
  if (!available.length) {
    select.append(new Option("No SQL Warehouses available", ""));
    select.disabled = true;
    return;
  }
  select.append(new Option("Choose a SQL Warehouse…", ""));
  for (const warehouse of available) {
    const label = `${warehouse.name || "Unnamed SQL warehouse"} · ${warehouse.state}`;
    const option = new Option(label, warehouse.warehouse_id);
    option.title = `${warehouse.warehouse_type || "SQL Warehouse"}${warehouse.size ? ` · ${warehouse.size}` : ""} · ${warehouse.warehouse_id}`;
    select.append(option);
  }
  select.disabled = false;
  select.value = state.selectedWarehouse;
}

function updateWarehouseMessage() {
  const panel = $("warehouse-message");
  panel.replaceChildren();
  const noWarehouses = !state.warehouses.length && ["EMPTY", "READY"].includes(state.warehouseStatus);
  const message = state.warehouseMessage || (noWarehouses
    ? "No SQL Warehouses are available for this Databricks identity. Remote SQL is unavailable; local queries and other Analytics capabilities remain available."
    : state.warehouseStatus === "DEGRADED" && !state.warehouses.length
      ? "Unable to refresh SQL Warehouses. Your local datasets and catalog remain available."
      : "");
  if (!message) { panel.classList.add("hidden"); return; }
  panel.classList.remove("hidden");
  panel.classList.toggle("error", state.warehouseStatus === "DEGRADED" || state.warehouseStatus === "STALE" || state.warehouseInvalidated);
  panel.append(node("span", "", message));
  const retry = button("Refresh", "warehouse-retry", () => loadWarehouses(true), "Retry SQL Warehouse discovery");
  panel.append(retry);
}

function chooseWarehouse(payload) {
  const items = payload.warehouses || [];
  const previous = state.selectedWarehouse || readStorage(WAREHOUSE_KEY, "");
  state.warehouses = items;
  state.warehouseStatus = payload.status || (items.length ? "READY" : "EMPTY");
  state.warehouseMessage = payload.error?.message || "";
  const previousItem = items.find((item) => item.warehouse_id === previous);
  if (previous && previousItem && !["DELETED", "UNAVAILABLE"].includes(previousItem.state)) {
    state.selectedWarehouse = previous;
    state.warehouseInvalidated = false;
  } else if (previous) {
    state.selectedWarehouse = "";
    state.warehouseInvalidated = true;
    state.warehouseMessage = "Previously selected SQL Warehouse is no longer available. Please choose another warehouse.";
    writeStorage(WAREHOUSE_KEY, "");
  } else if (!previous && !state.warehouseInvalidated) {
    const running = items.filter((item) => item.state === "RUNNING");
    const defaults = items.filter((item) => item.is_default === true);
    const chosen = running.length === 1 ? running[0]
      : defaults.length === 1 ? defaults[0]
        : items.length === 1 ? items[0] : null;
    state.selectedWarehouse = chosen?.warehouse_id || "";
    if (chosen) writeStorage(WAREHOUSE_KEY, chosen.warehouse_id);
  }
  if (payload.status === "EMPTY") state.warehouseMessage = "";
  renderWarehouseSelector();
  updateWarehouseMessage();
  const dbStatus = ["READY", "EMPTY"].includes(state.warehouseStatus) ? "READY"
    : state.warehouseStatus === "STALE" ? "DEGRADED" : "DEGRADED";
  setStatus("status-databricks", dbStatus, payload.error?.message || `${items.length} SQL Warehouses visible`);
  if (state.activeWorkspaceId.startsWith("table:")) renderTableWorkspace(queryWorkspace());
}

async function loadWarehouses(refresh = false) {
  const select = $("warehouse-select");
  if (select && !state.warehouses.length) {
    select.replaceChildren(new Option("Loading warehouses…", ""));
    select.disabled = true;
  }
  try {
    const result = refresh ? await post("/api/warehouses/refresh", {}) : await api("/api/warehouses");
    chooseWarehouse(result);
  } catch (error) {
    state.warehouseStatus = "DEGRADED";
    state.warehouseMessage = error.message;
    updateWarehouseMessage();
    renderWarehouseSelector();
    setStatus("status-databricks", "DEGRADED", error.message);
  }
  renderHome();
}

function showWarehouseRequired(message) {
  state.warehouseMessage = message;
  updateWarehouseMessage();
  $("warehouse-select").focus();
}

function warehouseIdForQuery() {
  return state.selectedWarehouse || "";
}

function updateAskContext() {
  const context = renderWorkspaceContext();
  const card = $("context-card");
  card.replaceChildren();
  const copy = node("div", "context-card-copy");
  if (context.source === "TABLE") {
    const columns = context.detail?.columns || [];
    copy.append(node("strong", "", tableName(context.title)), node("small", "", columns.length ? `${columns.length} columns` : "Metadata pending"));
    card.title = context.title;
  } else if (context.source === "QUERY") {
    const route = context.detail?.route;
    copy.append(node("strong", "", context.title), node("small", "", route ? `Route · ${String(route).toUpperCase()}` : "Current query"));
    card.title = `${context.detail.route} route · query text included`;
  } else {
    copy.append(node("strong", "", "General question"), node("small", "", "Select a table or query for context."));
    card.title = "No active object";
  }
  card.append(copy);
  renderAssistantActions(context);
  const welcome = $("chat-thread").querySelector(".welcome-message p");
  if (welcome) welcome.textContent = context.source === "TABLE" ? "Ask about this table or use a quick action."
    : context.source === "QUERY" ? "Ask about this query or its execution route."
      : "Select a table or query to add context, or ask a general analytics question.";
  $("chat-thread").querySelectorAll(".welcome-message .suggestion").forEach((item) =>
    item.classList.toggle("hidden", context.source !== "GENERAL"));
}

function renderAssistantActions(context) {
  const container = $("assistant-actions");
  container.replaceChildren();
  if (context.source === "TABLE") {
    container.append(button("Summarize", "assistant-action", () => sendChat(`Summarize ${context.title} and point out what metadata is still missing.`)));
    container.append(button("Profile table", "assistant-action", () => profileActiveTable()));
  } else if (context.source === "QUERY") {
    container.append(button("Explain route", "assistant-action", () => explainActiveQuery()));
    container.append(button("Ask about query", "assistant-action", () => sendChat("Explain the current SQL query and its execution route.")));
  }
}

function buildChatContext() {
  const table = activeTableWorkspace();
  const query = activeQueryWorkspace();
  const context = { table: table?.fullName || "", sql: query?.sql?.trim().slice(0, 4096) || "" };
  if (table?.detail?.columns) context.columns = table.detail.columns.map((item) => item.name).filter(Boolean).slice(0, 100);
  if (query) context.route = query.result?.route || query.route;
  const preview = table?.preview;
  if (preview?.rows) context.preview = { columns: preview.columns || [], rows: preview.rows.slice(0, 10) };
  return context;
}

function chatMessageElement(role, value) {
  const item = node("article", `chat-message ${role}`);
  item.append(node("div", "message-role", role === "user" ? "YOU" : "ANVIL"));
  const text = role === "assistant" ? node("div", "message-text markdown-body") : node("p", "message-text", value);
  if (role === "assistant") renderSafeMarkdown(text, value);
  item.append(text);
  return { item, text };
}

function addChatMessage(role, value) {
  const thread = $("chat-thread");
  if (thread.querySelector(".welcome-message")) thread.replaceChildren();
  const { item, text } = chatMessageElement(role, value);
  thread.append(item);
  thread.scrollTop = thread.scrollHeight;
  return text;
}

async function loadChatHistory(before = null) {
  try {
    const route = "/api/anvil/chat/history?limit=30" + (before ? `&before=${encodeURIComponent(before)}` : "");
    const history = await api(route);
    const items = Array.isArray(history.items) ? history.items : [];
    const thread = $("chat-thread");
    if (items.length && !before && !state.chatBusy && !thread.querySelector(".chat-message")) {
      thread.replaceChildren();
    }
    if (before) {
      const oldHeight = thread.scrollHeight;
      const fragment = document.createDocumentFragment();
      items.forEach((message) => fragment.append(chatMessageElement(message.role, message.content).item));
      thread.prepend(fragment);
      thread.scrollTop += thread.scrollHeight - oldHeight;
    } else if (!state.chatBusy && !thread.querySelector(".chat-message")) {
      items.forEach((message) => thread.append(chatMessageElement(message.role, message.content).item));
      thread.scrollTop = thread.scrollHeight;
    }
    state.chatNextBefore = history.next_before || null;
    $("load-older-chat").hidden = !state.chatNextBefore;
  } catch (error) { /* A temporarily unavailable history endpoint must not block the workspace. */ }
}

function renderSafeMarkdown(container, value) {
  container.replaceChildren();
  const lines = String(value || "").replace(/\r\n?/g, "\n").split("\n");
  const appendInline = (parent, text) => {
    const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g;
    let cursor = 0;
    for (const match of text.matchAll(pattern)) {
      if (match.index > cursor) parent.append(document.createTextNode(text.slice(cursor, match.index)));
      const token = match[0];
      let element;
      if (token.startsWith("`")) {
        element = node("code", "", token.slice(1, -1));
      } else if (token.startsWith("**")) {
        element = node("strong", "", token.slice(2, -2));
      } else if (token.startsWith("*")) {
        element = node("em", "", token.slice(1, -1));
      } else {
        const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
        let target;
        try { target = new URL(linkMatch[2], window.location.href); } catch { target = null; }
        if (!target || !["https:", "http:"].includes(target.protocol)) {
          parent.append(document.createTextNode(token));
          cursor = match.index + token.length;
          continue;
        }
        element = node("a", "", linkMatch[1]);
        element.href = target.href;
        element.target = "_blank";
        element.rel = "noopener noreferrer";
      }
      parent.append(element);
      cursor = match.index + token.length;
    }
    if (cursor < text.length) parent.append(document.createTextNode(text.slice(cursor)));
  };
  const isTableSeparator = (line) => line.includes("|") &&
    /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
  const tableCells = (line) => {
    const value = line.trim().replace(/^\|/, "").replace(/\|$/, "");
    const cells = [];
    let cell = "";
    let escaped = false;
    for (const char of value) {
      if (char === "|" && !escaped) { cells.push(cell.trim()); cell = ""; continue; }
      if (char === "\\" && !escaped) { escaped = true; cell += char; continue; }
      escaped = false;
      cell += char;
    }
    cells.push(cell.trim());
    return cells.map((entry) => entry.replaceAll("\\|", "|"));
  };
  for (let index = 0; index < lines.length;) {
    const line = lines[index];
    if (!line.trim()) { index += 1; continue; }
    if (line.startsWith("```")) {
      const code = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) code.push(lines[index++]);
      if (index < lines.length) index += 1;
      const pre = node("pre", "");
      pre.append(node("code", "", code.join("\n")));
      container.append(pre);
      continue;
    }
    if (index + 1 < lines.length && line.includes("|") && isTableSeparator(lines[index + 1])) {
      const headers = tableCells(line);
      const width = Math.min(headers.length, tableCells(lines[index + 1]).length);
      const table = node("table", "markdown-table");
      const head = node("thead", "");
      const headerRow = node("tr", "");
      for (const value of headers.slice(0, width)) {
        const cell = node("th", "");
        cell.scope = "col";
        appendInline(cell, value);
        headerRow.append(cell);
      }
      head.append(headerRow);
      const body = node("tbody", "");
      index += 2;
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        const values = tableCells(lines[index++]);
        const row = node("tr", "");
        for (let column = 0; column < width; column += 1) {
          const cell = node("td", "");
          appendInline(cell, values[column] || "");
          row.append(cell);
        }
        body.append(row);
      }
      table.append(head, body);
      const scroller = node("div", "markdown-table-scroll");
      scroller.setAttribute("role", "region");
      scroller.setAttribute("aria-label", "Scrollable answer table");
      scroller.tabIndex = 0;
      scroller.append(table);
      container.append(scroller);
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      const element = node(`h${heading[1].length}`, "");
      appendInline(element, heading[2]);
      container.append(element);
      index += 1;
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const list = node("ul", "");
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        const item = node("li", "");
        appendInline(item, lines[index++].replace(/^\s*[-*]\s+/, ""));
        list.append(item);
      }
      container.append(list);
      continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const list = node("ol", "");
      while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index])) {
        const item = node("li", "");
        appendInline(item, lines[index++].replace(/^\s*\d+\.\s+/, ""));
        list.append(item);
      }
      container.append(list);
      continue;
    }
    const paragraph = node("p", "");
    while (index < lines.length && lines[index].trim() &&
           !lines[index].startsWith("```") && !/^#{1,3}\s+/.test(lines[index]) &&
           !/^\s*[-*]\s+/.test(lines[index]) && !/^\s*\d+\.\s+/.test(lines[index])) {
      if (paragraph.childNodes.length) paragraph.append(document.createElement("br"));
      appendInline(paragraph, lines[index++]);
    }
    container.append(paragraph);
  }
}

async function sendChat(prefill = "") {
  const prompt = (prefill || $("chat-input").value).trim();
  if (!prompt || state.chatBusy) return;
  $("chat-input").value = "";
  resizeChatComposer();
  state.chatBusy = true;
  $("send-chat").disabled = true;
  addChatMessage("user", prompt);
  let answerText = "Preparing Analytics context…";
  const answer = addChatMessage("assistant", answerText);
  const activity = node("div", "assistant-activity");
  activity.setAttribute("role", "status");
  activity.setAttribute("aria-live", "polite");
  activity.append(node("span", "activity-spinner"), node("span", "", "Preparing Analytics session…"));
  answer.closest(".chat-message").insertBefore(activity, answer);
  answer.classList.add("hidden");
  const showAnswer = () => {
    activity.remove();
    answer.classList.remove("hidden");
  };
  let receivedText = false;
  try {
    await apiClient.streamChat({ prompt, context: buildChatContext(),
      deep_investigation: $("deep-investigation").checked }, (event, payload) => {
      if (event === "status") {
        activity.lastChild.textContent = payload.message || "Asking Anvil in the canonical session…";
        if (payload.model) {
          const badge = $("analytics-model-label");
          badge.textContent = `${payload.model.display_name} · ${payload.model.provider_name}`;
          badge.title = `Logical model: ${payload.model.logical_model}\nProvider: ${payload.model.provider_name}\nModel: ${payload.model.model_id}\nResolution: READY\nFallback: NONE`;
        }
      }
      if (event === "result") { showAnswer(); answerText = payload.text || ""; renderSafeMarkdown(answer, answerText); receivedText = true; }
      if (event === "chunk") {
        showAnswer();
        if (!receivedText) answerText = "";
        answerText += payload.text || "";
        renderSafeMarkdown(answer, answerText);
        receivedText = true;
      }
      $("chat-thread").scrollTop = $("chat-thread").scrollHeight;
    });
    if (!receivedText && answerText.startsWith("Preparing")) {
      showAnswer();
      answerText = "Anvil completed without a text response.";
      renderSafeMarkdown(answer, answerText);
    }
  } catch (error) {
    showAnswer();
    answerText = `I couldn't complete that request: ${error.message}`;
    renderSafeMarkdown(answer, answerText);
    toast(error.message, "error");
  } finally {
    state.chatBusy = false;
    $("send-chat").disabled = false;
    $("chat-input").focus();
  }
}

async function runQuery() {
  const workspace = activeQueryWorkspace();
  if (!workspace) return;
  workspace.sql = $("sql-editor").value.trim();
  workspace.route = $("query-route").value;
  workspace.error = "";
  if (!workspace.sql) {
    workspace.status = "failed";
    workspace.error = "Enter a read-only SQL query.";
    renderQueryWorkspace(workspace);
    return;
  }
  workspace.status = "running";
  workspace.result = null;
  workspace.message = workspace.route === "AUTO" ? "Checking local coverage…"
    : workspace.route === "LOCAL" ? "Preparing local query…" : "Preparing Databricks query…";
  renderQueryWorkspace(workspace);
  try {
    let explain = null;
    if (workspace.route === "AUTO") {
      explain = await post("/api/query/explain", { sql: workspace.sql });
      workspace.explain = explain;
      workspace.message = explain.route === "LOCAL" ? "Running query locally…" : "Preparing Databricks query…";
      renderQueryWorkspace(workspace);
      if (explain.route === "DATABRICKS" && !state.selectedWarehouse) {
        throw new Error("Select a SQL Warehouse for this query. Local queries remain available when coverage is complete.");
      }
    }
    const remoteRoute = workspace.route === "DATABRICKS" || (workspace.route === "AUTO" && explain?.route === "DATABRICKS");
    const selected = state.warehouses.find((item) => item.warehouse_id === warehouseIdForQuery());
    if (remoteRoute && selected && ["STOPPED", "STARTING", "STOPPING"].includes(selected.state)) {
      workspace.message = selected.state === "RUNNING" ? "Executing query on Databricks…" : "Starting SQL Warehouse…";
      renderQueryWorkspace(workspace);
    } else {
      workspace.message = explain?.route === "LOCAL" || workspace.route === "LOCAL"
        ? "Executing query locally…" : "Executing query on Databricks…";
      renderQueryWorkspace(workspace);
    }
    const result = await post("/api/query", { sql: workspace.sql, route: workspace.route,
      warehouse_id: warehouseIdForQuery(), timeout: 120 });
    workspace.result = result;
    workspace.status = "success";
    workspace.message = result.truncated ? "Result is bounded; refine your query for more detail." : "Query completed.";
    workspace.error = "";
    renderQueryWorkspace(workspace);
    updateAskContext();
    await loadRecentQueries();
  } catch (error) {
    workspace.status = error.name === "AbortError" ? "cancelled" : "failed";
    workspace.error = error.message;
    workspace.message = "Query could not be completed.";
    renderQueryWorkspace(workspace);
  }
}

async function explainActiveQuery() {
  const workspace = activeQueryWorkspace();
  if (!workspace?.sql) return;
  try {
    const result = await post("/api/query/explain", { sql: workspace.sql });
    addChatMessage("assistant", `This query will use ${result.route}. ${result.reason || ""}`.trim());
  } catch (error) { toast(error.message, "error"); }
}

async function profileActiveTable() {
  const workspace = activeTableWorkspace();
  if (!workspace) return;
  if (!state.selectedWarehouse) return showWarehouseRequired("Select a SQL Warehouse to profile this table.");
  try {
    const result = await api(`/api/tables/${encodeURIComponent(workspace.fullName)}/profile?warehouse_id=${encodeURIComponent(state.selectedWarehouse)}&limit=100`);
    const summary = (result.columns || []).slice(0, 10).map((column) => `${column.name}: ${column.distinct_in_sample} distinct, ${column.null_count} null`).join("\n");
    addChatMessage("assistant", result.status === "READY" ? `Profile of ${workspace.fullName}\n${summary || "No profile details were returned."}`
      : "Table profile is not available for this warehouse.");
  } catch (error) { addChatMessage("assistant", `Profile unavailable: ${error.message}`); }
}

function openMaterialize() {
  const workspace = activeTableWorkspace();
  if (!workspace) return toast("Open a table first.", "error");
  const columns = workspace.detail?.columns || [];
  $("materialize-title").textContent = workspace.coverage?.snapshot_id ? "Update local copy" : "Keep table available locally";
  $("materialize-columns").value = columns.slice(0, 5).map((item) => item.name).filter(Boolean).join(", ");
  $("materialize-all-columns").checked = false;
  $("materialize-selected-columns").checked = true;
  $("materialize-feedback").classList.remove("error");
  $("materialize-selected-field").classList.remove("hidden");
  $("materialize-columns").disabled = false;
  $("materialize-all-rows").checked = true;
  $("materialize-filtered-rows").checked = false;
  $("materialize-filter").value = "";
  $("materialize-filter").disabled = true;
  $("materialize-feedback").textContent = state.selectedWarehouse
    ? "Anvil reuses covered local data when possible. A warehouse starts only when a transfer is needed."
    : "Anvil selects an available warehouse only when a transfer is needed.";
  $("materialize-dialog").showModal();
}

async function startMaterialization() {
  const workspace = activeTableWorkspace();
  if (!workspace) return;
  const allColumns = $("materialize-all-columns").checked;
  const columns = allColumns ? ["*"] : $("materialize-columns").value.split(",").map((item) => item.trim()).filter(Boolean);
  const showFormError = (message, target) => {
    $("materialize-feedback").textContent = message;
    $("materialize-feedback").classList.add("error");
    target?.focus();
  };
  if (!columns.length) return showFormError("Please select at least one column.", $("materialize-columns"));
  const filteredRows = $("materialize-filtered-rows").checked;
  const predicate = filteredRows ? $("materialize-filter").value.trim() : "";
  if (filteredRows && !predicate) return showFormError("Enter a filter for filtered rows.", $("materialize-filter"));
  $("confirm-materialize").disabled = true;
  $("materialize-feedback").textContent = "Preparing local copy…";
  $("materialize-feedback").classList.remove("error");
  try {
    const operation = await post("/api/materializations", {
      source_name: workspace.fullName, columns, predicate,
      warehouse_id: state.selectedWarehouse || "",
    });
    if (operation.reused) {
      $("materialize-feedback").textContent = operation.message || "The current local copy covers this request.";
      await refreshCoverage(workspace);
      await loadHomeData();
      return;
    }
    workspace.activeOperation = operation.operation_id;
    workspace.operationPhase = operation.phase || operation.state;
    $("cancel-materialization").disabled = false;
    $("materialize-feedback").textContent = materializationPhaseText(workspace.operationPhase);
    renderTableWorkspace(workspace);
    pollMaterialization(operation.operation_id, workspace);
  } catch (error) { $("materialize-feedback").textContent = error.message; $("materialize-feedback").classList.add("error"); }
  finally { $("confirm-materialize").disabled = false; }
}

async function pollMaterialization(id, workspace) {
  if (workspace.activeOperation !== id) return;
  try {
    const operation = await api("/api/materializations/" + encodeURIComponent(id));
    workspace.operationPhase = operation.phase || operation.state;
    $("materialize-feedback").textContent = operation.state === "READY"
      ? "Local copy ready · " + Number(operation.rows || 0).toLocaleString() +
        " rows · " + formatBytes(operation.bytes || 0)
      : [materializationPhaseText(workspace.operationPhase),
         Number.isFinite(operation.percent) ? `${Number(operation.percent).toFixed(1)}%` : "",
         Number(operation.planned_rows || 0) > 0
           ? `${Number(operation.rows || 0).toLocaleString()} / ${Number(operation.planned_rows).toLocaleString()} rows`
           : Number(operation.rows || 0) > 0 ? `${Number(operation.rows).toLocaleString()} rows` : "",
         Number(operation.completed_chunks || 0) > 0 ? `${operation.completed_chunks} chunks` : "",
         Number(operation.bytes || 0) > 0 ? formatBytes(operation.bytes) : ""].filter(Boolean).join(" · ");
    if (["READY", "FAILED", "CANCELLED"].includes(operation.state)) {
      if (operation.state === "READY") {
        toast("Local copy is ready.", "success");
        await loadHomeData();
      }
      if (operation.state === "FAILED") {
        toast("Materialization failed. Review the operation details and retry when ready.", "error");
        $("materialize-feedback").textContent = `Failed · ${operation.failure_reason || operation.error_code || "transfer error"}. ${operation.resume_available ? "Resume keeps saved chunks." : "Retry starts a clean transfer."}`;
      }
      workspace.activeOperation = "";
      workspace.operationPhase = "";
      $("cancel-materialization").disabled = true;
      await refreshCoverage(workspace);
      return;
    }
    renderTableWorkspace(workspace);
  } catch (error) { $("materialize-feedback").textContent = error.message; }
  window.setTimeout(() => pollMaterialization(id, workspace), 1800);
}

async function retryMaterialization(operationId, resume = false) {
  try {
    const operation = await api(`/api/materializations/${encodeURIComponent(operationId)}/retry`, { method: "POST" });
    toast(resume ? "Resuming the saved download." : "A new materialization attempt has started.", "success");
    const workspace = queryWorkspace("table:" + (operation.source_name || ""));
    if (workspace) {
      workspace.activeOperation = operation.operation_id;
      workspace.operationPhase = operation.phase || operation.state;
      renderTableWorkspace(workspace);
      pollMaterialization(operation.operation_id, workspace);
    }
    await loadHomeData();
  } catch (error) { toast(error.message, "error"); }
}

function materializationPhaseText(phase) {
  const labels = {
    PLANNED: "Preparing local copy…",
    QUEUED: "Waiting for an available transfer worker…",
    STARTING_WAREHOUSE: "Starting SQL Warehouse…",
    SUBMITTING_QUERY: "Submitting Databricks query…",
    WAITING_FOR_RESULT: "Waiting for Databricks result…",
    RESULT_READY: "Databricks result is ready…",
    EXECUTING: "Executing Databricks query…",
    REMOTE_QUERY: "Executing Databricks query…",
    SUBMITTED: "Waiting for Databricks query…",
    FETCHING: "Preparing result transfer…",
    DOWNLOADING_ARROW: "Downloading Arrow data…",
    WRITING_PARQUET: "Writing local Parquet files…",
    VALIDATING: "Validating local copy…",
    ACTIVATING: "Activating local copy…",
    RUNNING: "Creating local copy…",
    PAUSED: "Local copy paused",
    RESUMABLE: "Download interrupted. Saved progress can be resumed.",
    FAILED: "Local copy failed",
    CANCELLED: "Local copy creation canceled",
    CANCELED: "Local copy creation canceled",
  };
  return labels[String(phase || "").toUpperCase()] || "Creating local copy…";
}

async function refreshCoverage(workspace) {
  try {
    workspace.coverage = await api(`/api/tables/${encodeURIComponent(workspace.fullName)}/coverage`);
    setLocalState(workspace.fullName, workspace.coverage.covered ? "full" : workspace.coverage.snapshot_id ? "partial" : "remote");
    renderTableWorkspace(workspace);
    renderHome();
  } catch { /* local state remains unknown */ }
}

async function loadRecentQueries() {
  try {
    const result = await api("/api/query/history?limit=10");
    state.queryHistory = result.items || [];
    renderHome();
  } catch { state.queryHistory = []; }
}

async function loadHomeData() {
  const results = await Promise.allSettled([
    api("/api/query/history?limit=10"),
    api("/api/datasets?limit=100"),
    api("/api/operations"),
    api("/api/investigations/recent?limit=5"),
  ]);
  state.queryHistory = results[0].status === "fulfilled" ? results[0].value.items || [] : [];
  state.datasets = results[1].status === "fulfilled" ? results[1].value.items || [] : [];
  state.operations = results[2].status === "fulfilled" ? results[2].value.items || [] : [];
  state.investigations = results[3].status === "fulfilled" ? results[3].value.items || [] : [];
  renderHome();
  if (state.catalogFilter === "local") renderCatalogView();
  renderOperationsFooter();
}

function renderOperationsFooter() {
  const active = state.operations.filter((item) => ["QUEUED", "PLANNED", "RUNNING", "PAUSED", "VALIDATING"].includes(item.state));
  const label = active.length ? `${active.length} active operation${active.length === 1 ? "" : "s"}` : "No active operations";
  $("operations-label").textContent = label;
  $("operations-label").title = active.map((item) => (item.source_name || "Local data") + ": " + item.state).join("\n") || "No active Analytics operations";
  $("operations-label").classList.toggle("hidden", !active.length);
}

function renderCatalogRefreshTime() {
  if (state.catalogSyncedAt) $("catalog-freshness").textContent = `Synced ${relativeTime(state.catalogSyncedAt)}`;
}

function panelMinimum(panelName) {
  if (window.innerWidth >= 3600) return panelName === "catalog" ? 340 : 420;
  if (window.innerWidth >= 2560) return panelName === "catalog" ? 300 : 370;
  return panelName === "catalog" ? 248 : 316;
}

function bindResize(handle, panelName) {
  const root = $("workspace-grid");
  const variable = panelName === "catalog" ? "--catalog-width" : "--assistant-width";
  const preference = panelName === "catalog" ? "catalogWidth" : "assistantWidth";
  const max = panelName === "catalog" ? 480 : 560;
  const widthFromPointer = (event) => {
    const rect = root.getBoundingClientRect();
    const width = panelName === "catalog" ? event.clientX - rect.left - 11
      : rect.right - event.clientX - 11;
    return Math.max(panelMinimum(panelName), Math.min(max, width));
  };
  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    handle.classList.add("dragging");
    handle.setPointerCapture(event.pointerId);
    const move = (next) => {
      const width = widthFromPointer(next);
      root.style.setProperty(variable, `${width}px`);
      state.layout[preference] = width;
    };
    const end = () => {
      handle.classList.remove("dragging");
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      writeStorage(LAYOUT_KEY, state.layout);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  });
  handle.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const current = state.layout[preference] || (panelName === "catalog" ? 280 : 360);
    const direction = panelName === "catalog" ? (event.key === "ArrowRight" ? 1 : -1) : (event.key === "ArrowLeft" ? 1 : -1);
    const width = Math.max(panelMinimum(panelName), Math.min(max, current + direction * 12));
    state.layout[preference] = width;
    root.style.setProperty(variable, `${width}px`);
    writeStorage(LAYOUT_KEY, state.layout);
  });
}

function applyLayout() {
  const root = $("workspace-grid");
  if (Number.isFinite(state.layout.catalogWidth)) root.style.setProperty("--catalog-width", `${Math.max(panelMinimum("catalog"), Math.min(480, state.layout.catalogWidth))}px`);
  if (Number.isFinite(state.layout.assistantWidth)) root.style.setProperty("--assistant-width", `${Math.max(panelMinimum("assistant"), Math.min(560, state.layout.assistantWidth))}px`);
  root.classList.toggle("catalog-collapsed", Boolean(state.layout.catalogCollapsed));
  root.classList.toggle("assistant-collapsed", Boolean(state.layout.assistantCollapsed));
  $("collapse-catalog").setAttribute("aria-expanded", String(!state.layout.catalogCollapsed));
  $("collapse-assistant").setAttribute("aria-expanded", String(!state.layout.assistantCollapsed));
  $("collapse-catalog").title = state.layout.catalogCollapsed ? "Expand catalog" : "Collapse catalog";
  $("collapse-assistant").title = state.layout.assistantCollapsed ? "Expand Ask Anvil" : "Collapse Ask Anvil";
}

function setQuerySplitRatio(value, persist = false) {
  const split = $("query-split");
  const divider = $("query-splitter");
  if (!split || !divider) return;
  const height = split.clientHeight - divider.offsetHeight;
  const min = height > 0 ? Math.max(0.25, 132 / height) : 0.25;
  const max = height > 0 ? Math.min(0.75, 1 - 116 / height) : 0.75;
  const bounded = Math.max(min, Math.min(Math.max(min, max), Number.isFinite(value) ? value : 0.62));
  split.style.setProperty("--query-editor-ratio", `${(bounded * 100).toFixed(2)}%`);
  divider.setAttribute("aria-valuenow", String(Math.round(bounded * 100)));
  if (persist) writeStorage(QUERY_SPLIT_KEY, bounded);
  window.anvilAnalyticsEditor?.layout?.();
  window.dispatchEvent(new Event("anvil:analytics-editor-resize"));
  return bounded;
}

function bindQuerySplitter() {
  const divider = $("query-splitter");
  const split = $("query-split");
  if (!divider || !split) return;
  const stored = readStorage(QUERY_SPLIT_KEY, 0.62);
  let ratio = setQuerySplitRatio(Number(stored));
  divider.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    divider.classList.add("dragging");
    divider.setPointerCapture(event.pointerId);
    const move = (next) => {
      const rect = split.getBoundingClientRect();
      const available = Math.max(1, rect.height - divider.offsetHeight);
      ratio = setQuerySplitRatio((next.clientY - rect.top) / available);
    };
    const end = () => {
      divider.classList.remove("dragging");
      divider.removeEventListener("pointermove", move);
      divider.removeEventListener("pointerup", end);
      divider.removeEventListener("pointercancel", end);
      setQuerySplitRatio(ratio, true);
    };
    divider.addEventListener("pointermove", move);
    divider.addEventListener("pointerup", end);
    divider.addEventListener("pointercancel", end);
  });
  divider.addEventListener("keydown", (event) => {
    if (!["ArrowUp", "ArrowDown"].includes(event.key)) return;
    event.preventDefault();
    ratio = setQuerySplitRatio(ratio + (event.key === "ArrowDown" ? 0.03 : -0.03), true);
  });
  window.addEventListener("resize", () => { ratio = setQuerySplitRatio(ratio); });
}

function togglePanel(panelName) {
  const key = panelName === "catalog" ? "catalogCollapsed" : "assistantCollapsed";
  state.layout[key] = !state.layout[key];
  applyLayout();
  writeStorage(LAYOUT_KEY, state.layout);
}

function installHandlers() {
  $("refresh-catalog").addEventListener("click", () => loadCatalog({ refresh: true }));
  $("home-refresh").addEventListener("click", async () => {
    await Promise.all([loadIdentity(), loadWarehouses(true), loadCatalog({ refresh: true }), loadHomeData()]);
  });
  $("catalog-search").addEventListener("input", (event) => {
    window.clearTimeout(window.catalogSearchTimer);
    window.catalogSearchTimer = window.setTimeout(() => searchCatalog(event.target.value), 160);
  });
  document.querySelectorAll(".catalog-filter").forEach((control) => control.addEventListener("click", () => {
    state.catalogFilter = control.dataset.catalogFilter;
    document.querySelectorAll(".catalog-filter").forEach((item) => {
      const active = item === control;
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    if (state.catalogFilter === "all" && state.catalogSearchTerm) searchCatalog(state.catalogSearchTerm);
    else renderCatalogView();
  }));
  $("new-query").addEventListener("click", () => createQuery());
  $("home-new-query").addEventListener("click", () => createQuery());
  $("table-new-query").addEventListener("click", () => createQuery(defaultSql(activeTableWorkspace()?.fullName || "")));
  $("favorite-table").addEventListener("click", () => {
    const workspace = activeTableWorkspace();
    if (workspace) toggleFavorite(workspace.fullName);
  });
  $("table-make-local").addEventListener("click", openMaterialize);
  document.querySelectorAll(".table-tab").forEach((tab) => tab.addEventListener("click", async () => {
    const workspace = activeTableWorkspace();
    if (!workspace) return;
    workspace.section = tab.dataset.section;
    renderTableWorkspace(workspace);
    if (workspace.section === "preview" && !workspace.preview) await loadTablePreview(workspace);
    if (workspace.section === "lineage" && !workspace.lineage) await loadTableLineage(workspace);
  }));
  $("run-query").addEventListener("click", runQuery);
  $("sql-editor").addEventListener("input", () => {
    const workspace = activeQueryWorkspace();
    if (workspace) workspace.sql = $("sql-editor").value;
    const lines = Math.max(1, $("sql-editor").value.split("\n").length);
    $("editor-gutter").textContent = Array.from({ length: lines }, (_, index) => index + 1).join("\n");
    updateAskContext();
  });
  $("query-route").addEventListener("change", () => {
    const workspace = activeQueryWorkspace();
    if (workspace) workspace.route = $("query-route").value;
  });
  $("warehouse-select").addEventListener("change", (event) => {
    state.selectedWarehouse = event.target.value;
    state.warehouseInvalidated = false;
    state.warehouseMessage = "";
    writeStorage(WAREHOUSE_KEY, state.selectedWarehouse);
    updateWarehouseMessage();
    updateAskContext();
    if (state.activeWorkspaceId.startsWith("table:")) renderTableWorkspace(queryWorkspace());
  });
  $("refresh-warehouses").addEventListener("click", () => loadWarehouses(true));
  $("send-chat").addEventListener("click", () => sendChat());
  $("load-older-chat").addEventListener("click", () => loadChatHistory(state.chatNextBefore));
  $("chat-input").addEventListener("input", resizeChatComposer);
  $("chat-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendChat(); }
  });
  const clearChatButton = $("clear-chat");
  const clearChatConfirm = $("clear-chat-confirm");
  clearChatButton.replaceChildren(icon("TRASH"));
  const closeClearConfirmation = () => {
    clearChatConfirm.hidden = true;
    clearChatButton.setAttribute("aria-expanded", "false");
  };
  clearChatButton.addEventListener("click", () => {
    const opening = clearChatConfirm.hidden;
    clearChatConfirm.hidden = !opening;
    clearChatButton.setAttribute("aria-expanded", String(opening));
    if (opening) $("cancel-clear-chat").focus();
  });
  $("cancel-clear-chat").addEventListener("click", () => {
    closeClearConfirmation();
    clearChatButton.focus();
  });
  $("confirm-clear-chat").addEventListener("click", async () => {
    const confirm = $("confirm-clear-chat");
    confirm.disabled = true;
    try {
      await post("/api/anvil/chat/clear");
      $("chat-thread").replaceChildren();
      const welcome = node("div", "welcome-message");
      welcome.append(node("div", "assistant-mark small", "✳"), node("p", "", "Start a new Ask Anvil conversation. Your saved Analytics context is still available."));
      $("chat-thread").append(welcome);
      state.chatNextBefore = null;
      $("load-older-chat").hidden = true;
      closeClearConfirmation();
      clearChatButton.focus();
    } catch (error) { toast(error.message, "error"); }
    finally { confirm.disabled = false; }
  });
  $("confirm-materialize").addEventListener("click", startMaterialization);
  $("materialize-all-columns").addEventListener("change", () => {
    const all = $("materialize-all-columns").checked;
    $("materialize-selected-field").classList.toggle("hidden", all);
    $("materialize-columns").disabled = all;
  });
  $("materialize-selected-columns").addEventListener("change", () => {
    $("materialize-selected-field").classList.remove("hidden");
    $("materialize-columns").disabled = false;
  });
  $("materialize-all-rows").addEventListener("change", () => {
    $("materialize-filter").disabled = !$("materialize-filtered-rows").checked;
  });
  $("materialize-filtered-rows").addEventListener("change", () => {
    $("materialize-filter").disabled = !$("materialize-filtered-rows").checked;
  });
  $("cancel-materialization").addEventListener("click", async () => {
    const workspace = activeTableWorkspace();
    if (!workspace?.activeOperation) return;
    try {
      await api(`/api/materializations/${encodeURIComponent(workspace.activeOperation)}/cancel`, { method: "POST" });
      $("materialize-feedback").textContent = "Cancellation requested.";
      $("cancel-materialization").disabled = true;
    } catch (error) { toast(error.message, "error"); }
  });
  document.querySelectorAll(".suggestion").forEach((item) => item.addEventListener("click", () => sendChat(item.dataset.prompt || "")));
  $("collapse-catalog").addEventListener("click", () => togglePanel("catalog"));
  $("collapse-assistant").addEventListener("click", () => togglePanel("assistant"));
  bindResize($("catalog-resize"), "catalog");
  bindResize($("assistant-resize"), "assistant");
  bindQuerySplitter();
  window.addEventListener("resize", applyLayout);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !clearChatConfirm.hidden) {
      closeClearConfirmation();
      clearChatButton.focus();
    }
    if (event.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) {
      event.preventDefault(); $("catalog-search").focus();
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "j") {
      event.preventDefault(); $("chat-input").focus();
    }
  });
  document.addEventListener("pointerdown", (event) => {
    if (!clearChatConfirm.hidden && !event.target.closest(".heading-actions")) closeClearConfirmation();
  });
}

async function start() {
  installHandlers();
  resizeChatComposer();
  applyLayout();
  renderWorkspaceTabs();
  renderCatalogView();
  renderHome();
  renderActiveWorkspace();
  updateAskContext();
  await Promise.all([loadIdentity(), loadCatalog(), loadWarehouses(), loadHomeData(), loadChatHistory()]);
  if (typeof window.anvilAnalyticsVisualSetup === "function") await window.anvilAnalyticsVisualSetup();
  window.setInterval(() => loadWarehouses(false), 60_000);
  window.setInterval(loadHomeData, 15_000);
  window.setInterval(renderCatalogRefreshTime, 60_000);
}

start();
