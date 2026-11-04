import { freshState, screens, modules, assets, labTemplates } from "./data.js";
import { escapeHtml, getAsset, getWorkspace, getLab, getPipeline, getNotebook, getRepository, getProduct, screenInfo, renderScreen, renderWorkspaceToolbar, renderExplorer, renderPrimaryNav, renderTabs, renderContext, renderStatusbar, renderModalContent } from "./views.js";

const STORAGE_KEY = "dexter.platform.demo.v1";
let state = loadState();
let pendingConnection = null;
let simulationTimers = new Map();
let toastTimer = 0;

function mergeState(base, saved) {
  if (!saved || typeof saved !== "object") return structuredClone(base);
  const out = structuredClone(base);
  for (const [key, value] of Object.entries(saved)) {
    if (value && typeof value === "object" && !Array.isArray(value) && out[key] && typeof out[key] === "object" && !Array.isArray(out[key])) out[key] = mergeState(out[key], value);
    else if (value !== undefined) out[key] = value;
  }
  return out;
}

function updateDemoOwnerName(value) {
  if (typeof value === "string") return value.replaceAll("Henrique Costa", "Henrique Silva");
  if (Array.isArray(value)) return value.map(updateDemoOwnerName);
  if (value && typeof value === "object") {
    for (const [key, nested] of Object.entries(value)) value[key] = updateDemoOwnerName(nested);
  }
  return value;
}

function loadState() {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    return updateDemoOwnerName(parsed?.version === 1 ? mergeState(freshState(), parsed) : freshState());
  } catch { return updateDemoOwnerName(freshState()); }
}

function persist() {
  try {
    const snapshot = structuredClone(state);
    snapshot.modal = null;
    delete snapshot.viewportWidth;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot));
  } catch (error) {
    showToast("Browser storage is full", "Close large tabs or reset the local demo state.", "error");
  }
}

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const byId = id => document.getElementById(id);
const idForScreen = screen => screens.find(item => item.id === screen);
const shortTime = () => new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
const nextId = prefix => `${prefix}-${Date.now().toString(36)}-${Math.floor(Math.random()*1000).toString(36)}`;
function defaultEndpoint(name) {
  const value=String(name).toLowerCase();
  return value.includes("sql")?"sqlserver.local:1433":value.includes("oracle")?"oracle.local:1521":value.includes("kafka")?"kafka.local:9092":value.includes("api")?"http://api.local:8080":value.includes("mongo")?"mongodb.local:27017":value.includes("postgres")?"postgres.local:5432":value.includes("mysql")?"mysql.local:3306":value.includes("storage")||value.includes("filesystem")?"/workspace/data":"localhost:8080";
}
function defaultComponentSettings(name) {
  const value=String(name).toLowerCase();
  const base={profile:"Standard demo",endpoint:defaultEndpoint(name)};
  if(value.includes("kafka"))return {...base,topic:"account_events",partitions:6,eventFormat:"Avro"};
  if(value.includes("api")||value.includes("graphql")||value.includes("webhook"))return {...base,basePath:"/v1/customers",method:"GET",responseStatus:200};
  if(value.includes("storage")||value.includes("filesystem")||value.includes("file"))return {...base,bucket:"dexter-local",fileFormat:"Parquet",partitionKey:"event_date"};
  if(value.includes("spark")||value.includes("processing"))return {...base,runtime:"PySpark Local",workers:2};
  if(value.match(/sql|oracle|postgres|mysql|mongo/))return {...base,database:"dexter_demo",schema:"public",seedRows:10000};
  return base;
}
function schemaComponentFor(name) {
  const value=String(name||"").toLowerCase();
  if(value.includes("kafka"))return "Kafka";
  if(value.includes("api")||value.includes("graphql")||value.includes("webhook"))return "REST API";
  if(value.includes("filesystem")||value.includes("storage")||value.includes("file"))return "Filesystem";
  if(value.includes("mongo"))return "MongoDB";
  if(value.includes("oracle"))return "Oracle";
  if(value.match(/sql|postgres|mysql/))return "SQL Server";
  return "";
}
function hydrateDemoState() {
  state.componentSettings=(state.customComponents||[]).map((name,index)=>({...defaultComponentSettings(name),...(state.componentSettings?.[index]||{})}));
  for(const pipeline of state.pipelines||[])pipeline.edges??=pipeline.nodes.slice(1).map((node,index)=>[pipeline.nodes[index].id,node.id]);
  state.orchestration??=freshState().orchestration;
  state.orchestration.tasks??=freshState().orchestration.tasks;
  state.orchestration.edges??=freshState().orchestration.edges;
  state.selectedTasks??=[];
}
hydrateDemoState();

function render({ focusSelector = "" } = {}) {
  const active = document.activeElement;
  const activeSelector = focusSelector || (active?.id ? `#${CSS.escape(active.id)}` : "");
  const caret = active && typeof active.selectionStart === "number" ? active.selectionStart : null;
  byId("primary-rail").innerHTML = renderPrimaryNav(state);
  byId("explorer").innerHTML = renderExplorer(state);
  byId("workspace-toolbar").innerHTML = renderWorkspaceToolbar(state);
  byId("view-root").innerHTML = renderScreen(state);
  byId("context-panel").innerHTML = renderContext(state);
  byId("statusbar").innerHTML = renderStatusbar(state);
  byId("tab-strip").innerHTML = renderTabs(state);
  byId("operation-count").textContent = String(state.operations.filter(op => !["Completed", "Failed", "Cancelled"].includes(op.state)).length);
  byId("workspace-select").innerHTML = state.workspaces.map(ws => `<option value="${ws.id}" ${ws.id === state.activeWorkspace ? "selected" : ""}>${escapeHtml(ws.name)}</option>`).join("");
  byId("environment-select").value = state.environment;
  byId("global-search").value = state.globalSearch || "";
  document.documentElement.dataset.theme = state.theme === "system"
    ? (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark")
    : state.theme;
  byId("view-scroll").scrollTop = Math.min(byId("view-scroll").scrollTop, 12000);
  applyLayout();
  renderModal();
  persist();
  if (activeSelector) {
    const focusTarget = $(activeSelector);
    if (focusTarget) {
      focusTarget.focus({ preventScroll: true });
      if (caret !== null && typeof focusTarget.setSelectionRange === "function") focusTarget.setSelectionRange(caret, caret);
    }
  }
}

function applyLayout() {
  const layout = byId("main-layout");
  layout.classList.toggle("explorer-collapsed", Boolean(state.explorerCollapsed));
  layout.classList.toggle("context-collapsed", Boolean(state.contextCollapsed));
  const width = window.innerWidth;
  const split = 5;
  if (width <= 980) {
    layout.style.gridTemplateColumns = width <= 620 ? "46px minmax(0,1fr)" : "52px minmax(0,1fr)";
    byId("explorer").hidden = false;
    return;
  }
  const compactDesktop = width >= 1511 && width < 2300;
  const narrowDesktop = width <= 1240;
  const mediumDesktop = width < 1511 && width > 1240;
  const rail = compactDesktop ? 56 : narrowDesktop ? 58 : 62;
  const explorerDefault = compactDesktop ? 220 : narrowDesktop ? 210 : mediumDesktop ? 232 : 254;
  const contextDefault = compactDesktop ? 276 : narrowDesktop ? 46 : mediumDesktop ? 292 : 330;
  const explorerLimit = compactDesktop ? 300 : narrowDesktop ? 260 : 390;
  const contextLimit = compactDesktop ? 380 : mediumDesktop ? 360 : 440;
  const explorer = state.explorerCollapsed ? 42 : state.explorerWidthUserSet ? Math.min(Math.max(190, Number(state.explorerWidth) || explorerDefault), explorerLimit) : explorerDefault;
  const context = state.contextCollapsed ? 44 : narrowDesktop ? 46 : state.contextWidthUserSet ? Math.min(Math.max(250, Number(state.contextWidth) || contextDefault), contextLimit) : contextDefault;
  layout.style.gridTemplateColumns = `${rail}px ${explorer}px ${split}px minmax(0,1fr) ${split}px ${context}px`;
  byId("explorer").hidden = false;
}

function responsiveBand(width) {
  if (width <= 620) return "mobile-small";
  if (width <= 980) return "mobile";
  if (width <= 1240) return "narrow";
  if (width < 1511) return "compact";
  if (width < 2300) return "full-hd";
  return "large";
}

let currentResponsiveBand = responsiveBand(window.innerWidth);
window.addEventListener("resize", () => {
  const nextBand = responsiveBand(window.innerWidth);
  if (nextBand === currentResponsiveBand) return;
  currentResponsiveBand = nextBand;
  applyLayout();
  if (state.screen === "pipeline-studio") render();
});

function renderModal() {
  const dialog = byId("modal");
  if (!state.modal) {
    if (dialog.open) dialog.close();
    return;
  }
  byId("modal-eyebrow").textContent = state.modal.eyebrow || "DEXTER · LOCAL DEMO";
  byId("modal-title").textContent = state.modal.title || modalTitle(state.modal.type);
  byId("modal-content").innerHTML = renderModalContent(state);
  if (!dialog.open) dialog.showModal();
  if (state.modal.type === "command") setTimeout(() => byId("command-search")?.focus(), 0);
}

function modalTitle(type) {
  return ({ "new-workspace": "Create workspace", "clear-chat": "Clear conversation", "reset-demo": "Reset demo", "new-product": "Create data product", "attach-asset": "Add assets to workspace", operation: "Operation details", notifications: "Notifications", command: "Go to", "confirm-action": "Confirm action", "delete-local": "Delete local snapshot" })[type] || "Dexter";
}

function showToast(title, detail = "", tone = "success") {
  const region = byId("toast-region");
  const element = document.createElement("div");
  element.className = `toast ${tone}`;
  element.innerHTML = `<span>${tone === "error" ? "!" : tone === "success" ? "✓" : "ⓘ"}</span><div><strong>${escapeHtml(title)}</strong>${escapeHtml(detail)}</div>`;
  region.append(element);
  setTimeout(() => element.remove(), 3600);
  clearTimeout(toastTimer);
}

function setModuleForScreen(screen) {
  const item = idForScreen(screen);
  if (!item) return "home";
  if (item.module === "Govern") return "govern";
  return modules.find(module => module.label === item.module)?.id || "home";
}

function openScreen(screen, { module = "", newTab = true, keepModule = false } = {}) {
  if (!idForScreen(screen)) screen = "home";
  state.screen = screen;
  if (screen === "schema-designer" && state.selectedComponent !== null) {
    const schemaComponent=schemaComponentFor(state.customComponents[state.selectedComponent]);
    if(schemaComponent)state.schemaComponent=schemaComponent;
  }
  if (module) state.activeModule = module;
  else if (!keepModule) state.activeModule = setModuleForScreen(screen);
  const info = idForScreen(screen);
  const existing = state.tabs.find(tab => tab.id === screen);
  if (!existing && newTab) state.tabs.push({ id: screen, title: info.title.replace("Development Lab Gallery", "Labs").replace("Multi-Environment Data Explorer", "Data Explorer"), dirty: false, environment: state.environment });
  if (existing && existing.environment === undefined) existing.environment = state.environment;
  state.activeTabEnvironment = (existing || state.tabs.find(tab => tab.id === screen))?.environment || state.environment;
  state.recentScreens = [screen, ...state.recentScreens.filter(id => id !== screen)].slice(0, 6);
  render();
}

function closeTab(screen) {
  if (screen === "home") return;
  const tab = state.tabs.find(item => item.id === screen);
  if (tab?.dirty && !confirm(`Discard unsaved changes in ${tab.title}?`)) return;
  state.tabs = state.tabs.filter(item => item.id !== screen);
  if (state.screen === screen) openScreen(state.tabs.at(-1)?.id || "home", { newTab: false });
  else render();
}

function openCommandPalette() {
  state.modal = { type: "command", title: "Go to screen or action" };
  render();
}

function setPath(path, value) {
  const parts = path.split(".");
  let target = state;
  for (const part of parts.slice(0, -1)) {
    if (!target[part] || typeof target[part] !== "object") target[part] = {};
    target = target[part];
  }
  target[parts.at(-1)] = value;
}

function applyModel(model, value, target) {
  if (model === "activeWorkspace") {
    state.activeWorkspace = value;
    const ws = state.workspaces.find(item => item.id === value);
    if (ws) state.selectedLab = ws.labId || state.selectedLab;
  } else if (model === "environment") state.environment = value;
  else if (model === "movement-source") state.selectedAsset = value;
  else if (model === "mock-service") {state.mockService=value;const name=value.toLowerCase();state.mockProfile=name.includes("kafka")?"streaming":name.includes("api")?"api":name.includes("storage")||name.includes("file")?"storage":"relational";}
  else if (model === "movement-environment") {state.movementEnvironment=value;const next=state.assets.find(asset=>asset.environment===value&&asset.environment!=="LOCAL");if(next)state.selectedAsset=next.id;}
  else if (model === "movement-catalog") {state.movementCatalog=value;const next=state.assets.find(asset=>asset.environment!=="LOCAL"&&asset.fullName.split(".")[0]===value);if(next)state.selectedAsset=next.id;}
  else if (model === "movement-destination") state.movementConfig.destination = value;
  else if (model === "movement-mode") state.movementConfig.mode = value;
  else if (model === "movement-rows") state.movementConfig.sampleRows = Number(value);
  else if (model === "movement-format") state.movementConfig.format = value;
  else if (model === "movement-ack") state.movementConfig.governanceAcknowledged = Boolean(target.checked);
  else if (model === "synthetic-source") state.syntheticConfig.source = value;
  else if (model === "synthetic-destination") state.syntheticConfig.destination = value;
  else if (model === "synthetic-rows") state.syntheticConfig.rows = Number(value);
  else if (model === "compare-left") state.compareAssets[0] = value;
  else if (model === "compare-right") state.compareAssets[1] = value;
  else if (model === "notebook-runtime") getNotebook(state).runtime = value;
  else if (model === "sql-route") state.sql.route = value;
  else if (model === "sql.text") state.sql.text = value;
  else if (model === "product.lifecycle") getProduct(state).status = value;
  else if (model === "selectedRepository") state.selectedRepository = value;
  else if (model === "lineage-asset" || model === "contract-asset" || model === "profile-asset") state.selectedAsset = value;
  else if (model === "theme") state.theme = value.toLowerCase().replace(" (demo)", "");
  else setPath(model, /^\d+$/.test(value) ? Number(value) : value);
  if (model === "sql.text") {
    const tab = state.tabs.find(item => item.id === "sql-workspace");
    if (tab) tab.dirty = true;
  }
}

function setDirty(screen = state.screen, dirty = true) {
  const tab = state.tabs.find(item => item.id === screen);
  if (tab) tab.dirty = dirty;
}

function simulateOperation(operation, { fail = false, success = null, failure = null, error = "" } = {}) {
  const steps = [18, 38, 59, 81, 100];
  let cursor = 0;
  operation.state = operation.type === "Materialization" ? "Reading Metadata" : operation.type === "Lab lifecycle" ? "Starting" : "Running";
  operation.progress = 4;
  persist(); render();
  const advance = () => {
    if (!state.operations.some(item => item.id === operation.id) || operation.state === "Cancelled") return;
    operation.progress = steps[cursor] ?? 100;
    operation.state = operation.type === "Materialization" ? (cursor < 1 ? "Reading Metadata" : cursor < 2 ? "Extracting" : cursor < 4 ? "Transferring" : "Registering") : operation.type === "Lab lifecycle" ? "Starting" : cursor < 3 ? "Running" : "Validating";
    operation.phase = operation.type === "Materialization" ? ["Reading source metadata", "Submitting query", "Downloading result chunks", "Registering local snapshot", "Ready"][cursor] : operation.type === "Pipeline run" ? ["Connecting to source", "Extracting rows", "Applying transformations", "Validating contract", "Publishing output"][cursor] : operation.type === "Synthetic generation" ? ["Validating constraints", "Sampling distributions", "Generating records", "Checking relationships", "Registering dataset"][cursor] : ["Preparing services", "Starting database", "Loading schemas", "Checking health", "Ready"][cursor];
    cursor += 1;
    if (cursor === steps.length) {
      if (fail) {
        operation.state = "Failed";
        operation.progress = 72;
        operation.error = error || "The source schema did not satisfy the required contract.";
        operation.phase = "Contract validation";
        operation.logs = [...(operation.logs || []), `${shortTime()} ERROR ${operation.error}`];
        if (failure) failure(operation);
      } else {
        operation.state = "Completed";
        operation.progress = 100;
        operation.phase = "Completed";
        operation.logs = [...(operation.logs || []), `${shortTime()} INFO simulated operation completed`];
        if (success) success(operation);
      }
      operation.completed = shortTime();
      simulationTimers.delete(operation.id);
      persist(); render();
      showToast(operation.state === "Completed" ? "Simulation completed" : "Simulation failed", operation.error || operation.target, operation.state === "Failed" ? "error" : "success");
      return;
    }
    persist(); render();
    const timer = setTimeout(advance, 620);
    simulationTimers.set(operation.id, timer);
  };
  const timer = setTimeout(advance, 620);
  simulationTimers.set(operation.id, timer);
}

function createOperation(type, target, extra = {}) {
  const operation = { id: nextId("op"), type, target, state: "Queued", progress: 0, phase: "Queued for local simulation", started: `Today, ${shortTime()}`, logs: [`${shortTime()} INFO local simulation queued`], ...extra };
  state.operations.unshift(operation);
  return operation;
}

function completeMaterialization(operation) {
  const source=state.assets.find(asset=>asset.id===operation.sourceAssetId)||state.assets.find(asset=>asset.fullName===operation.target);
  if(!source)return;
  const config=operation.movementConfig||state.movementConfig;
  const columns=config.columns?.length?config.columns:source.schema.map(field=>field[0]);
  const selectedIndexes=columns.map(name=>source.schema.findIndex(field=>field[0]===name)).filter(index=>index>=0);
  const schema=source.schema.filter(field=>columns.includes(field[0]));
  const localId=`local-${source.id}`;
  const rowCount=config.mode==="Sample rows"?Math.min(source.rows,Number(config.sampleRows)||50000):source.rows;
  const localAsset={...structuredClone(source),id:localId,name:`${source.name}_local`,fullName:`local.${source.domain.toLowerCase()}.${source.name}`,environment:"LOCAL",type:"Dataset",owner:"Henrique Silva",rows:rowCount,size:config.mode==="Sample rows"?`${Math.max(1,Math.round((Number.parseFloat(source.size)||1)*rowCount/Math.max(1,source.rows)))} MB`:source.size,description:`Local snapshot materialized from ${source.fullName}.`,schema,samples:source.samples.map(row=>selectedIndexes.map(index=>row[index])).filter(row=>row.length),sourceAssetId:source.id,local:true,localStatus:"Ready",localUpdated:`Today, ${shortTime()}`,format:config.format||"Parquet"};
  const existing=state.assets.find(asset=>asset.id===localId);
  if(existing)Object.assign(existing,localAsset);else state.assets.unshift(localAsset);
  source.local=true;source.localStatus="Ready";source.localUpdated=localAsset.localUpdated;
  const workspace=getWorkspace(state);if(!workspace.assets.includes(localId))workspace.assets.push(localId);
  operation.rows=`${Number(rowCount).toLocaleString()} / ${Number(rowCount).toLocaleString()} rows`;operation.bytes=`${localAsset.size} transferred`;operation.phase="Local snapshot registered";
}

function startMaterialization() {
  const asset=getAsset(state);
  if(asset.exportAllowed===false){state.movementStep=6;openScreen("movement-wizard");showToast("Policy blocked local export","Remote read permission does not grant local export.","error");return;}
  const operation=createOperation("Materialization",asset.fullName,{progress:0,rows:"0 / "+Number(asset.rows).toLocaleString()+" rows",bytes:"0 / "+asset.size,workspace:getWorkspace(state).name,sourceAssetId:asset.id,movementConfig:structuredClone(state.movementConfig)});
  state.movementStep=8;openScreen("operations");simulateOperation(operation,{success:()=>completeMaterialization(operation)});
}

function startPipelineRun() {
  const pipeline = getPipeline(state);
  const operation = createOperation("Pipeline run", pipeline.name, { progress: 0, workspace: getWorkspace(state).name, rows: "0 rows", pipelineId:pipeline.id, pipelineFailure:!state.sourceSchemaFixed&&pipeline.id==="customer-pipeline", logs: [`${shortTime()} INFO pipeline run accepted`, `${shortTime()} INFO logical graph contains ${pipeline.nodes.length} nodes`] });
  state.selectedOperation = operation.id;
  openScreen("execution-console");
  const broken = !state.sourceSchemaFixed && pipeline.id === "customer-pipeline";
  simulateOperation(operation, { fail: broken, error: "Required column customer_tier was missing from the SQL Server source schema.", success: () => { operation.rows = "2,842 rows published"; state.testReadiness = state.tests.every(test => test.state !== "Failed"); } });
}

function runTests() {
  const selected=state.tests.filter(test=>test.selected!==false);
  if(!selected.length){showToast("Select tests to run","Choose at least one test in the suite.","error");return;}
  state.tests = state.tests.map(test => test.selected===false ? test : ({ ...test, state: test.name.includes("source compatibility") && !state.sourceSchemaFixed ? "Failed" : test.name.includes("Runtime portability") ? "Warning" : "Passed", detail: test.name.includes("source compatibility") && !state.sourceSchemaFixed ? "customer_tier missing" : test.detail || "Deterministic mock evidence" }));
  state.testReadiness = state.tests.every(test => test.state !== "Failed");
  state.operations.unshift({ id: nextId("op-test"), type: "Test run", target: getWorkspace(state).name, state: state.testReadiness ? "Completed" : "Failed", progress: 100, phase: "Certification suite", started: `Today, ${shortTime()}`, logs: [`${shortTime()} INFO ${selected.length} checks evaluated`, `${shortTime()} ${state.testReadiness ? "INFO all selected checks passed" : "ERROR source schema contract mismatch"}`], error: state.testReadiness ? "" : "The customer_tier field is missing from the source schema." });
  render();
  showToast(state.testReadiness ? "Test suite passed" : "Test suite needs attention", `${state.tests.filter(t => t.state === "Passed").length} passed · ${state.tests.filter(t => t.state === "Failed").length} failed`, state.testReadiness ? "success" : "error");
}

function addSyntheticDataset() {
  const rows = Math.max(100, Number(state.syntheticConfig.rows) || 25000);
  const id = nextId("synthetic");
  const base = state.assets.find(asset => asset.id === state.syntheticConfig.source) || getAsset(state);
  const asset={ id, name: "customers_synthetic_" + shortTime().replace(":", ""), fullName: `local.${base.domain.toLowerCase()}.customers_synthetic_${id.slice(-5)}`, type: "Dataset", domain: base.domain, environment: "LOCAL", owner: "Henrique Silva", classification: "Synthetic", rows, size: `${Math.max(1, Math.round(rows * .00024))} MB`, updated: `Today, ${shortTime()}`, description: `Synthetic dataset generated from ${base.fullName} structure. No source records were copied.`, local: true, localStatus: "Ready", localUpdated: `Today, ${shortTime()}`, schema: structuredClone(base.schema), samples: structuredClone(base.samples) };
  const operation = createOperation("Synthetic generation", asset.fullName, { progress: 0, rows: `${rows.toLocaleString()} rows planned`, workspace: getWorkspace(state).name, resultAsset:asset, logs: [`${shortTime()} INFO schema-aware generation queued`, `${shortTime()} INFO no source row values will be copied`] });
  state.selectedOperation=operation.id;
  openScreen("operations");
  simulateOperation(operation,{success:()=>{
    if(!state.assets.some(item=>item.id===asset.id))state.assets.unshift(asset);
    const workspace=getWorkspace(state);
    if(!workspace.assets.includes(asset.id))workspace.assets.push(asset.id);
    operation.rows=`${rows.toLocaleString()} rows registered`;delete operation.resultAsset;
    state.selectedAsset=asset.id;
    openScreen("table-workbench");
    showToast("Synthetic dataset registered",`${rows.toLocaleString()} rows are available in LOCAL.`,"success");
  }});
  return operation;
}

function addPipelineNode(type) {
  const pipeline = getPipeline(state);
  const index = pipeline.nodes.length;
  const id = nextId("node");
  pipeline.nodes.push({ id, type, title: type === "Source" ? "New source" : type === "Destination" ? "New destination" : `New ${type.toLowerCase()}`, subtitle: "Configure input and output", x: 44 + (index % 5) * 205, y: 235 + Math.floor(index / 5) * 100 });
  state.selectedNode = id;
  state.tabs.find(tab => tab.id === "pipeline-studio") && (state.tabs.find(tab => tab.id === "pipeline-studio").dirty = true);
  render();
  showToast("Pipeline node added", `${type} node added to ${pipeline.name}.`);
}

function sendChat(prompt) {
  const clean = prompt.trim();
  if (!clean) return;
  state.chat.push({ role: "user", text: clean, time: shortTime() });
  const context = state.chatContext.map(id => state.assets.find(asset => asset.id === id)?.fullName || state.products.find(product => product.id === id)?.name || id);
  const currentAsset = getAsset(state);
  let response = "I can help with the selected workspace. Choose an asset, notebook, pipeline or execution to make the context more specific.";
  if (/diagnos|fail|error|why/i.test(clean)) response = `The latest ${state.operations.find(op => op.state === "Failed")?.type || "pipeline"} failure is specific: ${state.operations.find(op => op.state === "Failed")?.error || "a required field is missing"} Check the source schema against customer-profile-v3, then rerun the contract suite. Context shared: ${context.join(", ") || currentAsset.fullName}.`;
  else if (/sql|query/i.test(clean)) response = `For ${context[0] || currentAsset.fullName}, start with a bounded local query. Example: SELECT ${currentAsset.schema.slice(0,3).map(field => field[0]).join(", ")} FROM ${currentAsset.fullName} LIMIT 100. This is a proposal for the mock SQL editor; no query was run.`;
  else if (/schema|compare|column/i.test(clean)) response = `${currentAsset.fullName} has ${currentAsset.schema.length} demo fields. The customer profile contract expects customer_tier; the simulated SQL Server source is missing it. I recommend reconciling that schema before publishing.`;
  else if (/pipeline|improv|transform/i.test(clean)) response = `The selected customer pipeline currently validates contract v3 after normalization. Its last run failed because customer_tier is absent at the source. Add that field to the Lab schema, validate, then retry. Shared context: ${context.join(", ") || getPipeline(state).name}.`;
  else if (/synthetic|test data/i.test(clean)) response = `I can create deterministic synthetic records from ${currentAsset.fullName}. The preview preserves its field types and key relationships while avoiding source record values.`;
  else if (/lineage|impact/i.test(clean)) response = `${currentAsset.fullName} feeds customer_incremental_ingest and the Customer 360 product. A schema change here affects two transformations and one published output port.`;
  else if (/document|summary|pr/i.test(clean)) response = `The current change adds incremental customer ingestion, contract validation and checkpoint replay coverage. One source compatibility check still needs attention before the workspace is Ready for Review.`;
  else if (/generate pyspark|pyspark/i.test(clean)) response = `from pyspark.sql import functions as F\n\nprofile = spark.table("${currentAsset.fullName}")\nprofile = profile.withColumn("loaded_at", F.current_timestamp())\nprofile.select("customer_id", "customer_tier", "loaded_at")\n\nThis is a local development example. The runtime is simulated.`;
  const wantsProposal = /propose|suggest.*change|apply.*change|fix it|make the change/i.test(clean);
  const message = { role: "assistant", text: response, time: shortTime() };
  if (wantsProposal) message.proposal = { title: "Add customer_tier to source schema", description: "Extend the SQL Server Customers schema and preserve the profile contract v3 field.", affected: "Customer SQL Server Lab · customer_incremental_ingest", status: "pending" };
  state.chat.push(message);
  persist(); render();
}

function attachCurrentContext() {
  let id = state.selectedAsset;
  if (state.screen === "pipeline-studio") id = `${getPipeline(state).name} · ${getPipeline(state).nodes.find(n => n.id === state.selectedNode)?.title || "pipeline"}`;
  else if (state.screen === "notebook-studio") id = getNotebook(state).name;
  else if (state.screen === "lab-cockpit" || state.screen === "lab-composer") id = getLab(state).name;
  else if (state.screen === "product-builder" || state.screen === "product-catalog") id = getProduct(state).name;
  else if (state.screen === "repositories" || state.screen === "artifact-review") id = `${getRepository(state).path} · selected changes`;
  else if (state.screen === "execution-console") id = state.operations.find(op => op.id === state.selectedOperation)?.target || "latest execution logs";
  if (!state.chatContext.includes(id)) state.chatContext.push(id);
  state.contextTab = "assistant";
  state.contextCollapsed = false;
  render();
  showToast("Context attached", id, "success");
}

function action(actionName, element) {
  const id = element.dataset.id || "";
  const value = element.dataset.value || element.dataset.kind || "";
  const name = element.dataset.name || "";
  switch (actionName) {
    case "close-tab": closeTab(id); return true;
    case "open-command-palette": openCommandPalette(); return true;
    case "new-workspace": state.modal = { type: "new-workspace" }; render(); return true;
    case "create-product": state.modal = { type: "new-product" }; render(); return true;
    case "attach-asset": state.modal = { type: "attach-asset" }; render(); return true;
    case "open-operations": openScreen("operations"); return true;
    case "open-notifications": state.modal = { type: "notifications" }; render(); return true;
    case "user-menu": openScreen("settings"); showToast("Signed in as Henrique Silva", "Dexter demo user · local state only.", "info"); return true;
    case "close-modal": state.modal = null; render(); return true;
    case "clear-chat": state.modal = { type: "clear-chat" }; render(); return true;
    case "confirm-clear-chat": state.chat = []; state.modal = null; render(); showToast("Conversation cleared", "Workspace data and assets were preserved."); return true;
    case "confirm-reset": state.modal = { type: "reset-demo" }; render(); return true;
    case "reset-demo": for (const timer of simulationTimers.values()) clearTimeout(timer); simulationTimers.clear(); localStorage.removeItem(STORAGE_KEY); state = freshState(); hydrateDemoState(); pendingConnection = null; render(); resumeActiveOperations(); showToast("Demo reset", "Dexter has returned to its seeded state."); return true;
    case "toggle-explorer": case "collapse-explorer": state.explorerCollapsed = !state.explorerCollapsed; render(); return true;
    case "toggle-context": state.contextCollapsed = !state.contextCollapsed; render(); return true;
    case "context-tab": state.contextTab = value; render(); return true;
    case "attach-current-context": attachCurrentContext(); return true;
    case "remove-chat-context": state.chatContext.splice(Number(element.dataset.index),1); render(); return true;
    case "ask-suggestion": sendChat(element.dataset.prompt || "Explain the selected asset"); return true;
    case "open-asset": case "select-asset": state.selectedAsset = id; openScreen(actionName === "open-asset" ? "table-workbench" : state.screen); return true;
    case "open-workspace": {
      const ws = state.workspaces.find(item => item.id === id); if (ws) { state.activeWorkspace = ws.id; state.selectedLab = ws.labId || state.selectedLab; }
      openScreen("workspace-overview"); return true;
    }
    case "workspace-settings": state.modal = { type: "info", title: "Workspace settings" }; render(); return true;
    case "favorite-workspace": state.favorites = state.favorites.includes(id) ? state.favorites.filter(item => item !== id) : [...state.favorites,id]; render(); return true;
    case "favorite-asset": state.favorites = state.favorites.includes(id) ? state.favorites.filter(item => item !== id) : [...state.favorites,id]; render(); return true;
    case "open-product": {
      state.selectedProduct=id;const product=getProduct(state);
      state.productDraft={name:product.name,purpose:product.description,domain:product.domain,owner:product.owner,selectedAssets:[...product.assets],selectedPipelines:[...product.pipelines],selectedContracts:[...product.contracts],port:product.ports[0]||"",slo:product.slo,consumer:""};
      openScreen("product-builder");return true;
    }
    case "open-risk-product": return action("open-product",{dataset:{id:"risk-event-product"}});
    case "filter-all": state.workspaceFilter="all"; render(); return true;
    case "filter-favorites": state.workspaceFilter="favorites"; render(); return true;
    case "favorite-table": state.favorites = state.favorites.includes(state.selectedAsset)?state.favorites.filter(item=>item!==state.selectedAsset):[...state.favorites,state.selectedAsset]; render(); return true;
    case "asset-tab": state.assetTab = element.dataset.tab; render(); return true;
    case "navigate-compare": case "compare-assets": openScreen("table-compare"); return true;
    case "compare-recommendation": showToast("Compatibility review", "Schema comparison found changes that need contract review before promotion.", "info"); return true;
    case "navigate-contracts": openScreen("contracts"); return true;
    case "navigate-lineage": openScreen("lineage"); return true;
    case "navigate-test-center": openScreen("test-center"); return true;
    case "navigate-artifact-preview": openScreen("artifact-preview"); return true;
    case "navigate-orchestration": openScreen("orchestration"); return true;
    case "navigate-pr-wizard": state.delivery.stage = 1; openScreen("pr-wizard"); return true;
    case "navigate-schema": openScreen("schema-designer"); return true;
    case "navigate-mock-behavior": openScreen("mock-behavior"); return true;
    case "open-sql": {
      const asset=state.assets.find(item=>item.id===id)||getAsset(state);
      state.selectedAsset=asset.id;
      if (asset.environment==="LOCAL") state.sql.route="LOCAL";
      state.sql.text = `SELECT ${asset.schema.slice(0,3).map(col=>col[0]).join(", ")}\nFROM ${asset.fullName}\nLIMIT 100`;
      openScreen("sql-workspace"); return true;
    }
    case "open-notebook": if(id)state.selectedAsset=id;openScreen("notebook-studio");attachContextWithoutRender(getAsset(state).fullName);return true;
    case "insert-asset-notebook": {const asset=getAsset(state),notebook=getNotebook(state);notebook.cells.push({id:nextId("cell"),type:"sql",source:`SELECT *\nFROM ${asset.fullName}\nLIMIT 100`,output:null});setDirty("notebook-studio");render();showToast("Read cell inserted",`${asset.fullName} · ${asset.environment}`);return true;}
    case "open-synthetic": state.syntheticConfig.source=state.selectedAsset; openScreen("synthetic-studio"); return true;
    case "start-movement": state.movementStep = 1; openScreen("movement-wizard"); return true;
    case "movement-next": if (state.movementStep===6 && getAsset(state).exportAllowed===false) { showToast("Policy approval required","Local export remains blocked until a steward approves it.","error"); return true; } state.movementStep=Math.min(7,state.movementStep+1); render(); return true;
    case "movement-back": state.movementStep=Math.max(1,state.movementStep-1); render(); return true;
    case "cancel-movement": state.movementStep=1; openScreen("discover"); return true;
    case "run-materialization": startMaterialization(); return true;
    case "preview-local": state.selectedAsset=id; state.assetTab="Data Preview"; openScreen("table-workbench"); return true;
    case "refresh-local": {const local=state.assets.find(asset=>asset.id===id);const source=state.assets.find(asset=>asset.id===local?.sourceAssetId)||local;if(!source||source.environment==="LOCAL"){showToast("No remote source recorded","Synthetic datasets can be regenerated from Synthetic Data Studio.","info");return true;}state.selectedAsset=source.id;state.movementConfig.destination="Local workspace";state.movementConfig.format=local.format||"Parquet";state.movementConfig.mode="Full table";openScreen("movement-wizard");showToast("Refresh prepared",`Review the simulated materialization from ${source.fullName}.`,`info`);return true;}
    case "local-more": state.selectedAsset=id; state.localDeleteTarget=id; state.modal={type:"delete-local",title:"Delete local snapshot"}; render(); return true;
    case "confirm-delete-local": {
      const target=state.localDeleteTarget;
      if(!target){state.modal=null;render();return true;}
      state.assets=state.assets.filter(asset=>asset.id!==target);
      for(const workspace of state.workspaces) workspace.assets=workspace.assets.filter(assetId=>assetId!==target);
      for(const product of state.products) product.assets=product.assets.filter(assetId=>assetId!==target);
      state.productDraft.selectedAssets=state.productDraft.selectedAssets.filter(assetId=>assetId!==target);
      if(state.selectedAsset===target)state.selectedAsset=state.assets.find(asset=>asset.environment==="LOCAL")?.id||state.assets[0]?.id;
      state.modal=null;state.localDeleteTarget=null;render();showToast("Local snapshot deleted","The source asset and external data were left unchanged.","info");return true;
    }
    case "storage-details": openScreen("settings"); return true;
    case "use-lab-template": {
      const template=labTemplates.find(item=>item.id===id); if (template) { state.customComponents=[...template.components];state.componentSettings=state.customComponents.map(defaultComponentSettings);state.componentConnections=state.customComponents.slice(1).map((_,index)=>[index,index+1]);state.selectedComponents=[];state.selectedComponent=null;state.labTemplate=template.name; }
      openScreen("lab-composer"); return true;
    }
    case "create-custom-lab": state.customComponents=[]; state.componentSettings=[]; state.componentConnections=[]; state.selectedComponents=[]; state.selectedComponent=null; state.labTemplate="Custom Lab"; openScreen("lab-composer"); return true;
    case "add-component": if (!state.customComponents.includes(name)) {state.customComponents.push(name);state.componentSettings.push(defaultComponentSettings(name));} state.selectedComponent=state.customComponents.indexOf(name);state.selectedComponents=[state.selectedComponent]; render(); return true;
    case "select-component": {const index=Number(element.dataset.index);state.selectedComponent=index;state.selectedComponents??=[];state.selectedComponents=state.selectedComponents.includes(index)?state.selectedComponents.filter(item=>item!==index):[...state.selectedComponents.slice(-1),index];render();return true;}
    case "remove-component": if (state.selectedComponent!==null) { const index=state.selectedComponent;state.customComponents.splice(index,1);state.componentSettings.splice(index,1);state.componentConnections=state.componentConnections.filter(([a,b])=>a!==index&&b!==index).map(([a,b])=>[a>index?a-1:a,b>index?b-1:b]);state.selectedComponent=null;state.selectedComponents=[];render(); } else showToast("Select a component","Choose a service node to remove it.","info"); return true;
    case "connect-components": {const selected=state.selectedComponents||[];if(selected.length!==2){showToast("Select two services","Choose two topology nodes, then connect them.","info");return true;}const edge=[...selected].sort((a,b)=>a-b);state.componentConnections??=[];if(!state.componentConnections.some(([a,b])=>a===edge[0]&&b===edge[1]))state.componentConnections.push(edge);state.selectedComponents=[];render();showToast("Services connected",`${state.customComponents[edge[0]]} → ${state.customComponents[edge[1]]}`);return true;}
    case "validate-lab": {
      const problem=state.customComponents.length===0||state.customComponents.length>8;
      showToast(problem?"Lab validation needs attention":"Lab topology is valid",problem?"Add one to eight components before saving.":`${state.customComponents.length} services · resource requirements are within the local preview.` ,problem?"error":"success"); return true;
    }
    case "save-lab": {
      const id=nextId("lab"); const lab={id,name:state.labName||`${state.labTemplate||"Custom"} Lab`,template:state.labTemplate||"Custom Lab",status:"Stopped",components:[...state.customComponents],componentSettings:structuredClone(state.componentSettings),connections:structuredClone(state.componentConnections),schemas:[state.schemas[0].table],schema:structuredClone(state.schemas[0]),mockSettings:structuredClone(state.mockBehaviors||{}),endpoints:state.customComponents.map((component,i)=>state.componentSettings[i]?.endpoint||defaultEndpoint(component)),health:"Stopped",logs:[`${shortTime()}  Topology saved · ${state.customComponents.length} components`]};
      state.labs.unshift(lab); state.selectedLab=id; const ws=getWorkspace(state); ws.labId=id; openScreen("lab-cockpit"); showToast("Development Lab saved",`${lab.name} was added to ${ws.name}.`); return true;
    }
    case "lab-start": {
      const lab=getLab(state); if (lab.status==="Running") { showToast("Lab is already running",lab.name,"info"); return true; }
      const op=createOperation("Lab lifecycle",lab.name,{phase:"Starting services",progress:0,workspace:getWorkspace(state).name,lifecycleAction:"start",labId:lab.id}); lab.status="Starting"; render(); simulateOperation(op,{success:()=>{lab.status="Running";lab.health="Healthy";lab.logs.unshift(`${shortTime()}  Lab started · all ${lab.components.length} services healthy`);}}); return true;
    }
    case "lab-start-fail": {const lab=getLab(state);const op=createOperation("Lab lifecycle",`${lab.name} · failure scenario`,{phase:"Starting services",progress:0,lifecycleAction:"fail",labId:lab.id});lab.status="Starting";lab.health="Starting";render();simulateOperation(op,{fail:true,error:"Simulated port conflict on the local database endpoint.",failure:()=>{lab.status="Failed";lab.health="Unhealthy";lab.logs.unshift(`${shortTime()} ERROR simulated port conflict · ${lab.endpoints[0]||"localhost"}`);}});return true;}
    case "lab-stop": { const lab=getLab(state);if(lab.status==="Stopped"){showToast("Lab is already stopped",lab.name,"info");return true;}lab.status="Stopping";lab.health="Stopping";const op=createOperation("Lab lifecycle",`${lab.name} · stop`,{phase:"Stopping services",progress:0,lifecycleAction:"stop",labId:lab.id});render();simulateOperation(op,{success:()=>{lab.status="Stopped";lab.health="Stopped";lab.logs.unshift(`${shortTime()}  Lab stopped by user`);}});return true; }
    case "lab-restart": { const lab=getLab(state); lab.status="Starting"; lab.health="Starting"; const op=createOperation("Lab lifecycle",`${lab.name} · restart`,{phase:"Restarting services",progress:0}); render(); simulateOperation(op,{success:()=>{lab.status="Running";lab.health="Healthy";lab.logs.unshift(`${shortTime()}  Lab restarted · all services healthy`);}}); return true; }
    case "lab-reset": { const lab=getLab(state); lab.status="Stopped"; lab.health="Stopped"; lab.logs.unshift(`${shortTime()}  Lab state reset · demo data retained`); render(); showToast("Lab reset","Lab is stopped. Demo schemas were retained.","info"); return true; }
    case "copy-endpoints": case "copy-manifest": case "copy-artifact": case "copy-connection": {
      const text = actionName==="copy-endpoints" ? getLab(state).endpoints.join("\n") : actionName==="copy-manifest" ? `${getLab(state).name}\n${getLab(state).components.join("\n")}` : "# Dexter generated artifact preview";
      if(navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(()=>showToast("Copied to clipboard","Simulated configuration text was copied.")).catch(()=>showToast("Preview selected","Clipboard access is unavailable in this browser.","info"));
      else showToast("Preview selected",text,"info");
      return true;
    }
    case "import-schema": {
      const examples={
        "SQL Server":{table:"Customers",fields:[["customer_id","STRING","No","Primary key"],["email","STRING","Yes","PII · masked"],["created_at","TIMESTAMP","No","UTC"],["customer_tier","STRING","Yes","Gold, Silver, Bronze"]]},
        "Oracle":{table:"CUSTOMERS",fields:[["CUSTOMER_ID","STRING","No","Primary key"],["EMAIL","STRING","Yes","PII · masked"],["CREATED_AT","TIMESTAMP","No","UTC"],["CUSTOMER_TIER","STRING","Yes","Gold, Silver, Bronze"]]},
        "Kafka":{table:"account_events",fields:[["event_id","STRING","No","Event key · unique"],["account_id","STRING","No","Partition key"],["event_type","STRING","No","Event name"],["event_time","TIMESTAMP","No","Event-time field"],["risk_score","DECIMAL(12,2)","Yes","Enrichment output"]]},
        "REST API":{table:"GET /v1/customers/{customer_id}",fields:[["customer_id","STRING","No","Path parameter"],["include_history","BOOLEAN","Yes","Query parameter"],["status_code","INTEGER","No","Mock response status"],["profile","JSON","Yes","Response body"]]},
        "Filesystem":{table:"customer_profile.parquet",fields:[["record_id","STRING","No","Primary key"],["source_file","STRING","No","Input path"],["ingested_at","TIMESTAMP","No","Load timestamp"],["payload","JSON","Yes","Record body"]]},
        "MongoDB":{table:"customer_profiles",fields:[["_id","STRING","No","Document key"],["email","STRING","Yes","PII · masked"],["created_at","TIMESTAMP","No","UTC"],["attributes","JSON","Yes","Nested fields"]]}
      };
      const sample=examples[state.schemaComponent]||examples["SQL Server"];
      state.schemas[0].table=sample.table;state.schemas[0].fields=structuredClone(sample.fields);
      if(state.schemaComponent==="SQL Server"||state.schemaComponent==="Oracle")state.sourceSchemaFixed=true;
      render(); showToast("Bundled schema imported",`${state.schemaComponent} · ${sample.fields.length} fields`); return true;
    }
    case "add-schema-field": state.schemas[0].fields.push(["new_field","STRING","Yes","Description"]); render(); showToast("Schema field added","Edit the field and save the schema."); return true;
    case "delete-schema-field": state.schemas[0].fields.splice(Number(element.dataset.index),1); render(); return true;
    case "add-primary-key": state.schemas[0].fields.unshift(["id","STRING","No","Primary key"]); render(); return true;
    case "add-relationship": showToast("Relationship editor","Choose a source and foreign key in the schema table.","info"); return true;
    case "save-schema": setDirty("schema-designer",false); render(); showToast("Schema saved","The Lab schema and contract draft were updated."); return true;
    case "schema-parse": showToast("Schema validation passed",`${state.schemas[0].fields.length} fields parsed from the bundled sample.`); return true;
    case "schema-mode": state.schemaMode=element.dataset.mode; showToast(`${value[0].toUpperCase()+value.slice(1)} mode selected`,value==="import"?"Bundled import formats are supported.":"Schema editor mode updated.","info"); return true;
    case "preview-mock": state.mockPreview=`Today, ${shortTime()}`;render();showToast("Scenario preview updated",`${state.mockService} · ${(state.mockScenarios||[]).length} enabled scenarios.`);return true;
    case "save-mock": {state.mockSavedAt=`Saved today, ${shortTime()}`;const index=state.customComponents.indexOf(state.mockService);if(index>=0){state.componentSettings[index]??=defaultComponentSettings(state.mockService);state.componentSettings[index].profile=state.mockProfile;}state.mockBehaviors??={};state.mockBehaviors[state.mockService]={...state.mockSettings,profile:state.mockProfile,scenarios:[...(state.mockScenarios||[])]};const currentLab=state.labs.find(lab=>lab.id===state.selectedLab);if(currentLab){currentLab.mockSettings??={};currentLab.mockSettings[state.mockService]=structuredClone(state.mockBehaviors[state.mockService]);}render();showToast("Mock behavior saved",`${state.mockService} settings are attached to the Lab draft.`);return true;}
    case "mock-profile": {state.mockProfile=value;const terms={relational:["SQL Server","Oracle","PostgreSQL","MySQL","MongoDB"],streaming:["Kafka","Producer","Consumer"],api:["REST API","GraphQL","Webhook"],storage:["Filesystem","Local storage","Object storage"]};const candidate=state.customComponents.find(component=>terms[value]?.some(term=>component.toLowerCase().includes(term.toLowerCase())));if(candidate)state.mockService=candidate;render();showToast("Behavior profile selected",`${value} settings are available below.`,"info");return true;}
    case "validate-synthetic": showToast("Synthetic configuration valid",`${Number(state.syntheticConfig.rows).toLocaleString()} rows · relationships preserved.`); return true;
    case "refresh-synthetic-preview": showToast("Preview refreshed","Deterministic sample rows use the selected schema."); return true;
    case "generate-synthetic": addSyntheticDataset(); return true;
    case "run-notebook": {
      const notebook=getNotebook(state);
      for (const cell of notebook.cells) runCell(notebook,cell);
      const op=createOperation("Notebook run",notebook.name,{state:"Completed",progress:100,phase:"All cells completed",rows:`${notebook.cells.length} cells`,logs:[`${shortTime()} INFO notebook run completed · ${notebook.cells.length} cells`]});
      state.selectedOperation=op.id; render(); showToast("Notebook run completed",`${notebook.cells.length} cells · deterministic mock output.`); return true;
    }
    case "run-notebook-cell": {
      const notebook=getNotebook(state), cell=notebook.cells.find(c=>c.id===id); if (cell) { runCell(notebook,cell); render(); showToast("Cell executed",`${cell.type} output updated.`); } return true;
    }
    case "add-code-cell": case "add-markdown-cell": {
      const notebook=getNotebook(state); const type=actionName==="add-markdown-cell"?"markdown":"python";
      notebook.cells.push({id:nextId("cell"),type,source:type==="markdown"?"## New section\nDescribe the analysis here.":"# Write Python or SQL for the local demo\nprint('Hello from Dexter')",output:null}); setDirty("notebook-studio"); render(); return true;
    }
    case "remove-cell": { const notebook=getNotebook(state); notebook.cells=notebook.cells.filter(c=>c.id!==id); render(); return true; }
    case "move-cell": { const notebook=getNotebook(state),index=notebook.cells.findIndex(c=>c.id===id),next=index+(element.dataset.direction==="up"?-1:1); if(next>=0&&next<notebook.cells.length){[notebook.cells[index],notebook.cells[next]]=[notebook.cells[next],notebook.cells[index]];} render(); return true; }
    case "scroll-cell": document.querySelector(`[data-cell-id="${CSS.escape(id)}"]`)?.scrollIntoView({behavior:"smooth",block:"center"}); return true;
    case "save-notebook": setDirty("notebook-studio",false); showToast("Notebook saved","The portable notebook artifact is updated in this workspace."); return true;
    case "runtime-details": showToast("Runtime is simulated","No Python kernel or Databricks session was started.","info"); return true;
    case "run-sql": runSql(); return true;
    case "explain-sql": sendChat(`Explain this SQL: ${state.sql.text}`); return true;
    case "insert-asset-sql": { const asset=state.assets.find(a=>a.id===id); if(asset){state.selectedAsset=asset.id;state.sql.text=`SELECT * FROM ${asset.fullName} LIMIT 100`;if(asset.environment==="LOCAL")state.sql.route="LOCAL";render();} return true; }
    case "load-query": state.sql.text=state.sql.history[Number(element.dataset.index)]||state.sql.text; render(); return true;
    case "clear-query-history": state.sql.history=[]; render(); showToast("Query history cleared"); return true;
    case "add-pipeline-node": addPipelineNode(element.dataset.type||"Transform"); return true;
    case "select-pipeline-node": state.selectedNode=id; render(); return true;
    case "remove-pipeline-node": { const pipeline=getPipeline(state);pipeline.edges=(pipeline.edges||[]).filter(([from,to])=>from!==id&&to!==id);pipeline.nodes=pipeline.nodes.filter(n=>n.id!==id);state.selectedNode=pipeline.nodes[0]?.id||null;render();showToast("Pipeline node removed","Connected graph edges were removed with the node.");return true; }
    case "connect-pipeline-node": {
      const pipeline=getPipeline(state);pipeline.edges??=[];const index=pipeline.nodes.findIndex(n=>n.id===id);
      if(pipeline.nodes.length<2){showToast("Add another node","A connection needs two pipeline nodes.","info");return true;}
      const hasEdge=(from,to)=>pipeline.edges.some(edge=>edge[0]===from&&edge[1]===to);
      let pair=null;
      for(let i=index+1;i<pipeline.nodes.length&&!pair;i++)if(!hasEdge(id,pipeline.nodes[i].id))pair=[id,pipeline.nodes[i].id];
      for(let i=index-1;i>=0&&!pair;i--)if(!hasEdge(pipeline.nodes[i].id,id))pair=[pipeline.nodes[i].id,id];
      if(!pair){showToast("No missing adjacent dependency","The selected node already has its neighboring connection.","info");return true;}
      pipeline.edges.push(pair);render();showToast("Dependency connected",`${pipeline.nodes.find(n=>n.id===pair[0]).title} → ${pipeline.nodes.find(n=>n.id===pair[1]).title}`);return true;
    }
    case "validate-pipeline": { const pipeline=getPipeline(state),edges=pipeline.edges||[],broken=pipeline.nodes.some(n=>n.type==="Data Quality")&&!state.sourceSchemaFixed,disconnected=pipeline.nodes.length>1&&edges.length===0;const hasIssue=broken||disconnected;state.pipelineValidation={broken:hasIssue,message:broken?"Required field customer_tier is missing from the source schema.":disconnected?"Connect the pipeline nodes before running this graph.":`${pipeline.nodes.length} nodes · ${edges.length} dependencies · graph checks passed.`};render();showToast(hasIssue?"Pipeline validation needs attention":"Pipeline validation passed",state.pipelineValidation.message,hasIssue?"error":"success");return true; }
    case "preview-pipeline-order": showToast("Execution order",getPipeline(state).nodes.map((node,i)=>`${i+1}. ${node.title}`).join(" → "),"info"); return true;
    case "run-pipeline": startPipelineRun(); return true;
    case "select-pipeline": state.selectedPipeline=id; openScreen("pipeline-studio"); return true;
    case "select-notebook": state.selectedNotebook=id; openScreen("notebook-studio"); return true;
    case "component-profile": {const index=state.selectedComponent;if(index!==null){state.componentSettings[index]??={endpoint:defaultEndpoint(state.customComponents[index])};state.componentSettings[index].profile=value;render();}return true;}
    case "set-adapter": state.adapter=value; render(); showToast("Target adapter changed",`${value} preview was regenerated.`,"info"); return true;
    case "add-artifact": if(!state.selectedFiles.includes("orchestration/customer_incremental_ingest"))state.selectedFiles.push("orchestration/customer_incremental_ingest");openScreen("artifact-review");return true;
    case "select-artifact": state.selectedArtifact=name; showToast("Artifact selected",name,"info"); return true;
    case "validate-orchestration": {const config=state.orchestration,tasks=config.tasks||[],edges=config.edges||[],ids=new Set(tasks.map(task=>task.id));const invalid=edges.some(([from,to])=>from===to||!ids.has(from)||!ids.has(to));const cycle=edges.some(([from,to])=>edges.some(([nextFrom,nextTo])=>nextFrom===to&&nextTo===from));const issue=invalid||cycle;const message=invalid?"A dependency points to an invalid task or creates a self-reference.":cycle?"A dependency cycle was found.":`${tasks.length} tasks · ${edges.length} dependencies · ${config.retries} retries · workflow checks passed.`;showToast(issue?"Workflow validation needs attention":"Orchestration is valid",message,issue?"error":"success");return true;}
    case "contract-tab": state.contractTab=value; render(); return true;
    case "add-orchestration-task": {const config=state.orchestration;const task={id:nextId("task"),name:`New task ${config.tasks.length+1}`,kind:"Pipeline step"};config.tasks.push(task);state.selectedTaskId=task.id;state.selectedTasks=[task.id];render();showToast("Task added","The task is now part of the logical workflow graph.");return true;}
    case "remove-orchestration-task": {const config=state.orchestration;config.tasks=config.tasks.filter(task=>task.id!==id);config.edges=config.edges.filter(([from,to])=>from!==id&&to!==id);state.selectedTaskId=config.tasks[0]?.id||null;state.selectedTasks=[];render();showToast("Task removed","Its dependencies were removed from the workflow.");return true;}
    case "add-task-dependency": {const selected=state.selectedTasks||[];if(selected.length!==2){showToast("Select two tasks","Choose a source task, then a target task.","info");return true;}const [from,to]=selected;if(from===to||state.orchestration.edges.some(edge=>edge[0]===from&&edge[1]===to)){showToast("Dependency already exists","Choose a different task pair.","info");return true;}state.orchestration.edges.push([from,to]);state.selectedTasks=[];render();showToast("Dependency added",`${state.orchestration.tasks.find(task=>task.id===from)?.name} → ${state.orchestration.tasks.find(task=>task.id===to)?.name}`);return true;}
    case "select-task": {const taskId=element.dataset.id;state.selectedTaskId=taskId;state.selectedTasks??=[];state.selectedTasks=state.selectedTasks.includes(taskId)?state.selectedTasks.filter(item=>item!==taskId):[...state.selectedTasks.slice(-1),taskId];render();return true;}
    case "open-operation": state.selectedOperation=id; state.modal={type:"operation",id}; render(); return true;
    case "cancel-operation": {
      const op=state.operations.find(item=>item.id===id); if(op&&!['Completed','Failed','Cancelled'].includes(op.state)){op.state="Cancelled";op.phase="Cancelled by user";if(simulationTimers.has(id))clearTimeout(simulationTimers.get(id));simulationTimers.delete(id);render();showToast("Operation cancelled",op.target,"info");} else showToast("Operation is no longer active",op?.target||"","info");return true;
    }
    case "cancel-selected-operation": { const op=state.operations.find(item=>item.id===state.selectedOperation)||state.operations.find(item=>!['Completed','Failed','Cancelled'].includes(item.state)); if(op)return action("cancel-operation",{dataset:{id:op.id}});showToast("No active operation","There is nothing to cancel.","info");return true; }
    case "retry-operation": {
      const op=state.operations.find(item=>item.id===id);if(!op)return true;op.state="Queued";op.progress=0;op.error="";op.started=`Retried today, ${shortTime()}`;op.logs=[...(op.logs||[]),`${shortTime()} INFO retry accepted`]; const pipelineFail=op.type==="Pipeline run"&&!state.sourceSchemaFixed;simulateOperation(op,{fail:pipelineFail,error:"Required column customer_tier is still missing from the source schema.",success:()=>{op.rows="2,842 rows published";}});if(state.modal)state.modal=null;return true;
    }
    case "refresh-operations": render(); showToast("Operations refreshed","Local simulated state is current.","info"); return true;
    case "notification-open": { const n=state.notifications[Number(element.dataset.index)]; if(n){n.unread=false;state.modal=null;render(); if(n.title.includes("Pipeline"))openScreen("execution-console");else openScreen("operations");}return true; }
    case "mark-notifications-read": state.notifications.forEach(n=>n.unread=false);render();showToast("Notifications marked as read");return true;
    case "refresh-catalog": render(); showToast("Catalog refreshed","Demo metadata was refreshed locally."); return true;
    case "add-to-pipeline": { const pipeline=getPipeline(state); const asset=state.assets.find(item=>item.id===id)||getAsset(state);state.selectedAsset=asset.id;const nodeId=nextId("node");pipeline.nodes.push({id:nodeId,type:"Source",title:asset.name,subtitle:asset.fullName,x:44,y:Math.min(330,90+pipeline.nodes.length*65)});pipeline.edges??=[];state.selectedNode=nodeId;openScreen("pipeline-studio");showToast("Source node added",`${asset.fullName} · ${asset.environment}`);return true; }
    case "add-to-product": { const asset=getAsset(state); if(!state.productDraft.selectedAssets.includes(asset.id))state.productDraft.selectedAssets.push(asset.id);openScreen("product-builder");showToast("Asset added to product draft",asset.fullName);return true; }
    case "save-product": {
      const product=getProduct(state); product.name=state.productDraft.name||product.name;product.description=state.productDraft.purpose||product.description;product.domain=state.productDraft.domain||product.domain;product.owner=state.productDraft.owner||product.owner;product.assets=[...new Set(state.productDraft.selectedAssets)];product.pipelines=[...new Set(state.productDraft.selectedPipelines)];product.contracts=[...new Set(state.productDraft.selectedContracts||product.contracts)];product.ports=state.productDraft.port?[state.productDraft.port]:product.ports;product.slo=state.productDraft.slo||product.slo;if(state.productDraft.consumer&&!product.consumers.includes(state.productDraft.consumer))product.consumers.push(state.productDraft.consumer);product.status=product.status==="Published"?"Published":"Draft";render();showToast("Product draft saved","Linked assets and pipelines are visible in lineage.");return true;
    }
    case "validate-product": showToast(state.testReadiness?"Product is ready for review":"Product needs validation",state.testReadiness?"Assets and contract evidence are available.":"Resolve the failing source compatibility test.",state.testReadiness?"success":"error"); return true;
    case "add-consumer": state.productDraft.consumer="Marketing Activation";render();return true;
    case "create-contract": case "new-contract": showToast("Contract draft created","A new draft is attached to the selected asset."); return true;
    case "save-contract": showToast("Contract draft saved","Changes remain in this browser demo.");return true;
    case "add-contract-field": state.schemas[0].fields.push(["new_required_field","STRING","No","Contract draft"]);render();return true;
    case "run-tests": runTests(); return true;
    case "configure-tests": showToast("Test suite configuration","Select categories and scenarios in the Test & Certification Center.","info"); return true;
    case "refresh-profile": render();showToast("Profile refreshed","Summary metrics use deterministic sample data.");return true;
    case "suggest-quality-rules": sendChat(`Suggest quality rules for ${getAsset(state).fullName}`);return true;
    case "lineage-upstream": state.lineageDirection="upstream";render();showToast("Upstream lineage","Showing the source systems and upstream datasets.","info");return true;
    case "lineage-downstream": state.lineageDirection="downstream";render();showToast("Downstream lineage","Showing transformations, products and consumers.","info");return true;
    case "lineage-node": state.lineageSelected=Number(element.dataset.index);state.contextTab="properties";render();return true;
    case "lineage-depth": state.lineageDepth=value;render();return true;
    case "select-repository": state.selectedRepository=id;render();return true;
    case "ask-diagnose": attachContextWithoutRender(state.operations.find(op=>op.id===state.selectedOperation)?.target||"customer_incremental_ingest failure logs");state.contextTab="assistant";state.contextCollapsed=false;sendChat("Diagnose the failed pipeline run");return true;
    case "associate-repository": { const repo=getRepository(state); if(repo.access==="Restricted"){showToast("Repository is restricted","Request access from the owning team.","error");return true;}getWorkspace(state).repository=repo.path;render();showToast("Repository associated",`${repo.path} is linked to ${getWorkspace(state).name}.`);return true; }
    case "connect-repository": state.modal={type:"info",title:"Connect repository · simulated"};render();return true;
    case "browse-branches": state.modal={type:"info",title:`Branches · ${getRepository(state).path}`};render();return true;
    case "select-file": state.selectedFile=name;openScreen("artifact-review");return true;
    case "open-selected-file": showToast("Artifact preview","Generated file content is available in the diff view.","info");return true;
    case "diff-mode": state.diffMode=value;render();return true;
    case "pr-next": if(state.delivery.stage===7){createPullRequest();return true;} if(state.delivery.stage===1&&getRepository(state).access==="Restricted"){showToast("Repository access required","Select a repository with simulated write access.","error");return true;} if(state.delivery.stage===3&&state.selectedFiles.length===0){showToast("Select at least one artifact","Include a generated file for review.","error");return true;} state.delivery.stage=Math.min(7,state.delivery.stage+1);render();return true;
    case "pr-back": state.delivery.stage=Math.max(1,state.delivery.stage-1);render();return true;
    case "cancel-pr": openScreen("artifact-review");return true;
    case "open-pr": showToast(`Pull Request #${id}`,"Review and merge state are simulated in this local prototype.","info");return true;
    case "advance-pr": {
      const pr=state.prs.find(item=>String(item.number)===id);if(!pr)return true;
      const transitions={"Draft":"Ready for Review","Ready for Review":"Checks Running","Checks Running":"Approved","Approved":"Merged","Changes Requested":"Ready for Review","Merged":"Merged"};pr.state=transitions[pr.state]||"Ready for Review";pr.checks=pr.state==="Checks Running"?"3 / 3":pr.checks;render();showToast("Pull Request status updated",`#${pr.number} · ${pr.state}`);return true;
    }
    case "save-settings": showToast("Settings saved","Preferences are stored in this browser.");return true;
    case "configure-connections": showToast("Connection settings","All listed connections are mock-only in this prototype.","info");return true;
    case "toggle-switch": element.classList.toggle("on");return true;
    case "create-quick": {
      const workspace=getWorkspace(state);
      if(value==="pipeline"){
        const id=nextId("pipeline");const pipeline={id,name:"untitled_pipeline",description:"New technology-agnostic data pipeline.",status:"Draft",nodes:[]};
        state.pipelines.unshift(pipeline);workspace.pipelineIds.unshift(id);state.selectedPipeline=id;state.pipelineValidation=null;openScreen("pipeline-studio");showToast("Pipeline created","A new pipeline was added to this workspace.");
      } else if(value==="notebook"){
        const id=nextId("notebook");const notebook={id,name:"untitled_notebook.ipynb",runtime:"Python Local",cells:[{id:nextId("cell"),type:"markdown",source:"# New analysis\\nDescribe the question this notebook explores.",output:null},{id:nextId("cell"),type:"python",source:"# Start with a local dataset\\n",output:null}]};
        state.notebooks.unshift(notebook);workspace.notebookIds.unshift(id);state.selectedNotebook=id;openScreen("notebook-studio");showToast("Notebook created","A new local notebook was added to this workspace.");
      } else openScreen("lab-gallery");
      return true;
    }
    case "notification": state.modal={type:"notifications"};render();return true;
    case "refresh-warehouses": showToast("Warehouse list updated","Databricks connection is simulated.","info");return true;
    case "filter-operations": state.operationFilter=value;render();return true;
    case "filter-executions": state.executionFilter=value;render();return true;
    case "filter-product-domain": state.productDomain=value;openScreen("product-catalog");return true;
    case "add-code": openScreen("notebook-studio");return true;
    case "preview-proposal": showToast("Proposed change preview","The source schema would gain customer_tier and update the Lab contract draft.","info");return true;
    case "accept-proposal": {
      const msg=state.chat[Number(element.dataset.index)];if(msg?.proposal){msg.proposal.status="Accepted";state.sourceSchemaFixed=true;const schema=state.schemas[0].fields;if(!schema.some(field=>field[0]==="customer_tier"))schema.push(["customer_tier","STRING","Yes","Added from Ask Dexter proposal"]);const customer=state.assets.find(a=>a.id==="customers");if(customer&&!customer.schema.some(field=>field[0]==="customer_tier"))customer.schema.push(["customer_tier","STRING","NULL",""]);render();showToast("Proposed change accepted","Source schema and local demo contract were updated.");}return true;
    }
    case "reject-proposal": { const msg=state.chat[Number(element.dataset.index)];if(msg?.proposal)msg.proposal.status="Rejected";render();showToast("Proposed change rejected","No shared asset was modified.","info");return true; }
    case "confirm-generic": state.modal=null;render();showToast("Action simulated","The mock state was not connected to an external service.","info");return true;
    default: return false;
  }
}

function attachContextWithoutRender(id) {
  if (!state.chatContext.includes(id)) state.chatContext.push(id);
  persist();
}

function runCell(notebook, cell) {
  const source = cell.source.toLowerCase();
  if (cell.type === "markdown") { cell.output = "Markdown rendered in the notebook view."; return; }
  if (source.includes("group by customer_tier") || source.includes("group by channel")) cell.output = "channel        transactions   revenue\nweb            2,273,902      84,218,440.12\nstore          1,762,884      63,101,502.54\npartner          678,002      21,201,188.90\n\n3 rows · DuckDB Local · 142 ms";
  else if (source.includes("profile completeness") || source.includes("quality_rate")) cell.output = "Profile completeness: 98.2%\n\n1 warning · customer_tier null ratio is 1.8%";
  else if (source.includes("late_event_rate")) cell.output = "Late events: 3.4%\n\nWatermark: 15 minutes · 2,104 events outside the window";
  else if (source.includes("print")) cell.output = "Hello from Dexter\n\nExecuted with deterministic local demo output.";
  else cell.output = `Output simulated for ${notebook.runtime}.\n${cell.source.split("\n").at(-1)}\n\nNo real kernel was started.`;
}

function runSql() {
  const query=state.sql.text.trim();
  if(!query){showToast("Enter a query first","SQL Workspace requires a statement.","error");return;}
  if(/drop\s+|delete\s+|update\s+|insert\s+/i.test(query)){showToast("Read-only SQL","Mutating statements are disabled in the prototype.","error");return;}
  state.sql.history=[query,...state.sql.history.filter(item=>item!==query)].slice(0,12);
  const queryLower=query.toLowerCase();
  const referenced=state.assets.find(asset=>queryLower.includes(asset.fullName.toLowerCase()))||getAsset(state);
  const route=state.sql.route==="AUTO"?(queryLower.includes("local.")||referenced.environment==="LOCAL"||referenced.local?"LOCAL":"DATABRICKS"):state.sql.route;
  let columns, rows;
  if(/count\s*\(\s*\*\s*\)/i.test(query)) { columns=["count_star()"]; rows=[[queryLower.includes("transactions")?"4,714,788":Number(referenced.rows).toLocaleString()]]; }
  else if(/channel/i.test(query)) { columns=["channel","transactions","revenue"]; rows=[["web","2,273,902","84,218,440.12"],["store","1,762,884","63,101,502.54"],["partner","678,002","21,201,188.90"]]; }
  else { columns=referenced.schema.map(field=>field[0]); rows=referenced.samples.map(row=>row.map(value=>String(value))); }
  state.sqlResult={columns,rows,route,duration:"142 ms",query};
  const operation=createOperation("SQL query",query.split("\n")[0].slice(0,65),{state:"Completed",progress:100,phase:"Results ready",rows:`${rows.length} rows`,logs:[`${shortTime()} INFO ${route} route selected`,`${shortTime()} INFO deterministic demo result returned`]});
  state.selectedOperation=operation.id;
  setDirty("sql-workspace",false);
  render();
  showToast("Query completed",`${rows.length} rows · ${route} simulated result.`);
}

function createPullRequest() {
  const repo=getRepository(state);
  if(repo.access==="Restricted"){showToast("Repository access required","Select an accessible mock repository.","error");return;}
  const number=Math.max(284,...state.prs.map(pr=>pr.number))+1;
  const pr={number,title:state.delivery.title||"Customer ingestion changes",repository:repo.name,branch:state.delivery.featureBranch||getWorkspace(state).branch,state:"Checks Running",checks:state.testReadiness?"2 / 3":"1 / 3",created:`Today, ${shortTime()}`,workspace:getWorkspace(state).name,files:[...state.selectedFiles],evidence:state.tests.map(test=>({name:test.name,state:test.state}))};
  state.prs.unshift(pr); state.modal=null; state.delivery.stage=1; openScreen("delivery-status"); showToast(`Pull Request #${number} created`,"Simulated locally · no Git or CI call occurred.");
}

function updateFilter(target) {
  const value=target.value;
  const filterState={assets:"discoverSearch",workspaces:"workspaceSearch",labs:"labSearch",products:"productSearch",repositories:"repositorySearch"};
  if(target.id==="global-search") state.globalSearch=value;
  if(filterState[target.dataset.filter]) state[filterState[target.dataset.filter]]=value;
  if(target.dataset.filter==="explorer") {
    const query=value.toLowerCase();
    $$("#explorer .explorer-link, #explorer .tree-row").forEach(row=>row.hidden=!row.textContent.toLowerCase().includes(query));
    return;
  }
  if(target.dataset.filter==="sql-assets") {
    const query=value.toLowerCase();
    $$("#view-root .tree-row").forEach(row=>row.hidden=!row.textContent.toLowerCase().includes(query));
    return;
  }
  if(target.id==="command-search") {
    const query=value.toLowerCase();
    $$("#command-results .palette-result").forEach(row=>row.hidden=!row.textContent.toLowerCase().includes(query));
    return;
  }
  render({focusSelector: target.id?`#${CSS.escape(target.id)}`:`[data-filter="${CSS.escape(target.dataset.filter)}"]`});
}

function handleChange(target) {
  if(target.hasAttribute("data-filter-environment")){state.discoverEnvironment=target.value;render();return;}
  if(target.hasAttribute("data-filter-domain")){state.discoverDomain=target.value;render();return;}
  if(target.hasAttribute("data-lab-category")){state.labCategory=target.value;render();return;}
  if(target.hasAttribute("data-product-domain")){state.productDomain=target.value;render();return;}
  if(target.hasAttribute("data-product-status")){state.productStatus=target.value;render();return;}
  if(target.hasAttribute("data-repository-provider")){state.repositoryProvider=target.value;render();return;}
  if(target.hasAttribute("data-repository-domain")){state.repositoryDomain=target.value;render();return;}
  if(target.dataset.componentProperty!==undefined){
    const index=Number(target.dataset.componentIndex);state.componentSettings[index]??={profile:"Standard demo",endpoint:defaultEndpoint(state.customComponents[index])};
    const property=target.dataset.componentProperty;
    if(property==="name"){state.customComponents[index]=target.value;if(!state.componentSettings[index].endpoint||state.componentSettings[index].endpoint==="localhost:8080")state.componentSettings[index].endpoint=defaultEndpoint(target.value);}
    else state.componentSettings[index][property]=target.value;
    render();return;
  }
  if(target.dataset.model) {
    applyModel(target.dataset.model,target.type==="checkbox"?target.checked:target.value,target);
    if(target.dataset.model==="movement-source") state.selectedAsset=target.value;
    render();return;
  }
  if(target.dataset.adapter!==undefined){state.adapter=target.value;render();return;}
  if(target.dataset.column){const col=target.dataset.column;const checked=target.checked;state.movementConfig.columns=checked?[...new Set([...state.movementConfig.columns,col])]:state.movementConfig.columns.filter(item=>item!==col);render();return;}
  if(target.dataset.schemaField!==undefined){const row=state.schemas[0].fields[Number(target.dataset.schemaField)];if(row)row[Number(target.dataset.col)]=target.value;if(target.dataset.col==="0"&&target.value==="customer_tier")state.sourceSchemaFixed=true;persist();return;}
  if(target.dataset.nodeProperty){const node=getPipeline(state).nodes.find(item=>item.id===target.dataset.nodeId);if(node){node[target.dataset.nodeProperty]=target.value;setDirty("pipeline-studio");render();}return;}
  if(target.dataset.taskProperty){const task=state.orchestration.tasks.find(item=>item.id===target.dataset.taskId);if(task){task[target.dataset.taskProperty]=target.value;persist();if(target.tagName==="SELECT")render();}return;}
  if(target.dataset.cellId){const cell=getNotebook(state).cells.find(item=>item.id===target.dataset.cellId);if(cell){cell.source=target.value;setDirty("notebook-studio");persist();}return;}
  if(target.dataset.fileSelect!==undefined){const file=target.dataset.fileSelect;state.selectedFiles=target.checked?[...new Set([...state.selectedFiles,file])]:state.selectedFiles.filter(item=>item!==file);render();return;}
  if(target.dataset.productAsset){const list=state.productDraft.selectedAssets;state.productDraft.selectedAssets=target.checked?[...new Set([...list,target.dataset.productAsset])]:list.filter(id=>id!==target.dataset.productAsset);persist();return;}
  if(target.dataset.productPipeline){const list=state.productDraft.selectedPipelines;state.productDraft.selectedPipelines=target.checked?[...new Set([...list,target.dataset.productPipeline])]:list.filter(id=>id!==target.dataset.productPipeline);persist();return;}
  if(target.dataset.productContract){const list=state.productDraft.selectedContracts||[];state.productDraft.selectedContracts=target.checked?[...new Set([...list,target.dataset.productContract])]:list.filter(id=>id!==target.dataset.productContract);persist();return;}
  if(target.dataset.testSelect!==undefined){state.tests[Number(target.dataset.testSelect)].selected=target.checked;persist();return;}
  if(target.dataset.syntheticOption){const option=target.dataset.syntheticOption;state.syntheticOptions=target.checked?[...new Set([...(state.syntheticOptions||[]),option])]:state.syntheticOptions.filter(item=>item!==option);persist();return;}
  if(target.dataset.mockScenario){const scenario=target.dataset.mockScenario;state.mockScenarios=target.checked?[...new Set([...(state.mockScenarios||[]),scenario])]:state.mockScenarios.filter(item=>item!==scenario);render();return;}
  if(target.id==="workspace-select"){state.activeWorkspace=target.value;const ws=getWorkspace(state);state.selectedLab=ws.labId||state.selectedLab;render();return;}
  if(target.id==="environment-select"){state.environment=target.value;render();return;}
  if(target.id==="resourceSettings.cpu"||target.dataset.model==="resourceSettings.cpu"){state.resourceSettings.cpu=Number(target.value);render();return;}
  persist();
}

function handleInput(target) {
  if(target.dataset.model) {
    if(target.dataset.model==="sql.text"){state.sql.text=target.value;setDirty("sql-workspace");const numbers=$(".line-numbers");if(numbers)numbers.innerHTML=target.value.split("\n").map((_,i)=>i+1).join("<br>");persist();return;}
    if(target.dataset.model.startsWith("productDraft.")){applyModel(target.dataset.model,target.value,target);persist();return;}
    if(target.dataset.model.startsWith("delivery.")){applyModel(target.dataset.model,target.value,target);persist();return;}
    if(target.dataset.model.startsWith("mockSettings.")||target.dataset.model.startsWith("resourceSettings.")||target.dataset.model.startsWith("orchestration.")){applyModel(target.dataset.model,target.value,target);persist();return;}
  }
  if(target.dataset.cellId){const cell=getNotebook(state).cells.find(item=>item.id===target.dataset.cellId);if(cell){cell.source=target.value;setDirty("notebook-studio");persist();}return;}
  if(target.dataset.nodeProperty){const node=getPipeline(state).nodes.find(item=>item.id===target.dataset.nodeId);if(node){node[target.dataset.nodeProperty]=target.value;setDirty("pipeline-studio");persist();}return;}
  if(target.dataset.taskProperty){const task=state.orchestration.tasks.find(item=>item.id===target.dataset.taskId);if(task){task[target.dataset.taskProperty]=target.value;persist();}return;}
  if(target.dataset.componentProperty!==undefined){const index=Number(target.dataset.componentIndex);state.componentSettings[index]??={profile:"Standard demo",endpoint:defaultEndpoint(state.customComponents[index])};if(target.dataset.componentProperty==="name")state.customComponents[index]=target.value;else state.componentSettings[index][target.dataset.componentProperty]=target.value;persist();return;}
  if(target.dataset.schemaField!==undefined){const row=state.schemas[0].fields[Number(target.dataset.schemaField)];if(row){row[Number(target.dataset.col)]=target.value;if(row[0]==="customer_tier")state.sourceSchemaFixed=true;persist();}return;}
  if(target.id==="global-search"||target.dataset.filter||target.id==="command-search") updateFilter(target);
}

function handleForm(form,event) {
  event.preventDefault(); const data=new FormData(form); const type=form.dataset.form;
  if(type==="chat"){sendChat(String(data.get("prompt")||""));form.reset();return;}
  if(type==="new-workspace") {
    const name=String(data.get("name")||"").trim();if(!name)return;
    const id=nextId("workspace");const workspace={id,name,domain:String(data.get("domain")||"Customer"),description:String(data.get("description")||"New local-first engineering workspace."),color:"amber",repository:String(data.get("repository")||"Not connected"),branch:"feature/initial-work",updated:"Just now",labId:null,assets:[],pipelineIds:[],notebookIds:[],testReadiness:"Not run"};
    state.workspaces.unshift(workspace);state.activeWorkspace=id;state.modal=null;openScreen("workspace-overview");showToast("Workspace created",`${name} is ready for assets and engineering work.`);return;
  }
  if(type==="new-product") {
    const name=String(data.get("name")||"").trim();if(!name)return;
    const id=nextId("product");const domain=String(data.get("domain")||"Customer");const product={id,name,domain,owner:"Henrique Silva",status:"Draft",description:String(data.get("purpose")||"New governed data product."),assets:[],pipelines:[],contracts:[],ports:[],consumers:[],slo:"99% daily freshness",quality:"Not evaluated"};state.products.unshift(product);state.selectedProduct=id;state.productDraft={name,purpose:product.description,domain:product.domain,owner:product.owner,selectedAssets:[],selectedPipelines:[],selectedContracts:[],port:"",slo:product.slo};state.modal=null;openScreen("product-builder");showToast("Data product created",`${name} is a draft in the ${product.domain} domain.`);return;
  }
  if(type==="attach-asset") {
    const workspace=getWorkspace(state);
    workspace.assets=[...new Set([...workspace.assets,...data.getAll("assetIds").map(String)])];
    state.modal=null;render();showToast("Workspace assets updated",`${workspace.assets.length} assets are linked to ${workspace.name}.`);return;
  }
}

function dragStart(event) {
  const node=event.target.closest(".pipeline-node");if(!node)return;
  event.dataTransfer?.setData("text/plain",node.dataset.id); if(event.dataTransfer)event.dataTransfer.effectAllowed="move";
}

function dragEnd(event) {
  const element=event.target.closest(".pipeline-node");if(!element)return;
  const canvas=byId("pipeline-canvas"),rect=canvas.getBoundingClientRect();const node=getPipeline(state).nodes.find(item=>item.id===element.dataset.id);if(!node)return;
  const scale=window.innerWidth>=1511&&window.innerWidth<2300 ? .82 : 1;
  node.x=Math.max(15,Math.round(((event.clientX-rect.left+canvas.scrollLeft-80)/scale)/10)*10);node.y=Math.max(15,Math.round((event.clientY-rect.top+canvas.scrollTop-25)/10)*10);state.selectedNode=node.id;setDirty("pipeline-studio");render();
}

function resizeStart(event) {
  const separator=event.target.closest("[data-split]");if(!separator)return;
  separator.classList.add("dragging");separator.setPointerCapture(event.pointerId);
  const side=separator.dataset.split;
  const onMove=moveEvent=>{if(side==="explorer"){state.explorerWidth=Math.max(190,Math.min(390,moveEvent.clientX-byId("primary-rail").getBoundingClientRect().width));state.explorerWidthUserSet=true;}else{state.contextWidth=Math.max(250,Math.min(440,window.innerWidth-moveEvent.clientX));state.contextWidthUserSet=true;}applyLayout();};
  const onUp=()=>{separator.classList.remove("dragging");separator.removeEventListener("pointermove",onMove);separator.removeEventListener("pointerup",onUp);persist();};
  separator.addEventListener("pointermove",onMove);separator.addEventListener("pointerup",onUp);
}

document.addEventListener("click", event => {
  const actionElement=event.target.closest("[data-action]");
  if(actionElement && action(actionElement.dataset.action,actionElement)){event.preventDefault();return;}
  const screenElement=event.target.closest("[data-screen]");
  if(screenElement){event.preventDefault();const screen=screenElement.dataset.screen;if(screen==="table-workbench"&&screenElement.dataset.id)state.selectedAsset=screenElement.dataset.id;if(screen==="pipeline-studio"&&screenElement.dataset.id)state.selectedPipeline=screenElement.dataset.id;if(screen==="notebook-studio"&&screenElement.dataset.id)state.selectedNotebook=screenElement.dataset.id;const module=screenElement.dataset.module||"";openScreen(screen,{module});if(state.modal?.type==="command")state.modal=null;render();return;}
  const moduleElement=event.target.closest("[data-module]");
  if(moduleElement){openScreen(moduleElement.dataset.screen,{module:moduleElement.dataset.module});return;}
  if(event.target===byId("modal")){state.modal=null;render();}
});

document.addEventListener("change", event=>handleChange(event.target));
document.addEventListener("input", event=>handleInput(event.target));
document.addEventListener("submit", event=>{const form=event.target.closest("[data-form]");if(form)handleForm(form,event);});
document.addEventListener("dragstart",dragStart);
document.addEventListener("dragend",dragEnd);
document.addEventListener("pointerdown",resizeStart);
document.addEventListener("keydown",event=>{
  if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==="k"){event.preventDefault();openCommandPalette();return;}
  if(event.key==="Escape"&&state.modal){state.modal=null;render();return;}
  if((event.metaKey||event.ctrlKey)&&event.key==="Enter"&&state.screen==="sql-workspace"){event.preventDefault();runSql();}
  if(event.key==="Enter"&&event.target.id==="global-search"){
    const query=event.target.value.toLowerCase();const item=screens.find(screen=>screen.title.toLowerCase().includes(query));const asset=state.assets.find(candidate=>candidate.fullName.toLowerCase().includes(query)||candidate.name.toLowerCase().includes(query));
    if(item)openScreen(item.id);else if(asset){state.selectedAsset=asset.id;openScreen("table-workbench");}else openCommandPalette();
  }
  if(event.key==="Enter"&&event.target.id==="command-search"){
    const query=event.target.value.toLowerCase();const match=screens.find(screen=>screen.title.toLowerCase().includes(query));if(match){state.modal=null;openScreen(match.id);}
  }
});
byId("modal").addEventListener("cancel",event=>{event.preventDefault();state.modal=null;render();});
byId("workspace-select").addEventListener("change",event=>{state.activeWorkspace=event.target.value;state.selectedLab=getWorkspace(state).labId||state.selectedLab;render();});
byId("environment-select").addEventListener("change",event=>{state.environment=event.target.value;render();});

function resumeActiveOperations() {
  for(const operation of [...state.operations].filter(item=>!["Completed","Failed","Cancelled"].includes(item.state))) {
    if(operation.type==="Materialization")simulateOperation(operation,{success:()=>completeMaterialization(operation)});
    else if(operation.type==="Synthetic generation"&&operation.resultAsset)simulateOperation(operation,{success:()=>{const asset=operation.resultAsset;if(!state.assets.some(item=>item.id===asset.id))state.assets.unshift(asset);if(!getWorkspace(state).assets.includes(asset.id))getWorkspace(state).assets.push(asset.id);operation.rows=`${Number(asset.rows).toLocaleString()} rows registered`;delete operation.resultAsset;}});
    else if(operation.type==="Lab lifecycle") {const lab=state.labs.find(item=>item.id===operation.labId)||state.labs.find(item=>operation.target.startsWith(item.name));if(operation.lifecycleAction==="fail")simulateOperation(operation,{fail:true,error:"Simulated port conflict on the local database endpoint.",failure:()=>{if(lab){lab.status="Failed";lab.health="Unhealthy";}}});else simulateOperation(operation,{success:()=>{if(lab){lab.status=operation.lifecycleAction==="stop"?"Stopped":"Running";lab.health=lab.status==="Running"?"Healthy":"Stopped";}}});}
    else simulateOperation(operation,{fail:Boolean(operation.pipelineFailure),error:"Required source contract was not satisfied after session restore."});
  }
}

function initialize() {
  render();
  resumeActiveOperations();
  const initialHash=location.hash.replace(/^#/,"");
  if(initialHash.startsWith("screen=")){const screen=initialHash.slice(7);if(idForScreen(screen))openScreen(screen);}
  window.addEventListener("hashchange",()=>{const screen=location.hash.replace(/^#screen=/,"");if(idForScreen(screen)&&screen!==state.screen)openScreen(screen);});
  console.info("Dexter demo initialized",{screens:screens.length,assets:state.assets.length,simulation:"local-only"});
}

initialize();
