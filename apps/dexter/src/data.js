export const modules = [
  { id: "home", label: "Home", icon: "home", screens: ["home"] },
  { id: "workspaces", label: "Workspaces", icon: "workspace", screens: ["workspaces", "workspace-overview"] },
  { id: "discover", label: "Discover", icon: "discover", screens: ["discover", "table-workbench", "table-compare", "synthetic-studio", "local-data", "movement-wizard"] },
  { id: "build", label: "Build", icon: "build", screens: ["lab-gallery", "lab-composer", "schema-designer", "mock-behavior", "lab-resources", "lab-cockpit", "notebook-studio", "sql-workspace", "pipeline-studio", "orchestration", "artifact-preview", "execution-console", "test-center"] },
  { id: "products", label: "Data Products", icon: "products", screens: ["product-catalog", "product-builder"] },
  { id: "operate", label: "Operate", icon: "operate", screens: ["operations", "lineage", "contracts", "profiling"] },
  { id: "deliver", label: "Deliver", icon: "deliver", screens: ["repositories", "artifact-review", "pr-wizard", "delivery-status"] },
  { id: "govern", label: "Govern", icon: "govern", screens: ["contracts", "profiling", "lineage"] },
  { id: "settings", label: "Settings", icon: "settings", screens: ["settings"] }
];

export const screens = [
  ["home", "Platform Home", "Home"],
  ["workspaces", "Workspace Explorer", "Workspaces"],
  ["workspace-overview", "Workspace Overview", "Workspaces"],
  ["discover", "Multi-Environment Data Explorer", "Discover"],
  ["table-workbench", "Table Workbench", "Discover"],
  ["table-compare", "Table Compare", "Discover"],
  ["synthetic-studio", "Synthetic Data Studio", "Discover"],
  ["local-data", "Local Data Manager", "Discover"],
  ["movement-wizard", "Data Movement Wizard", "Discover"],
  ["lab-gallery", "Development Lab Gallery", "Build"],
  ["lab-composer", "Create Development Lab", "Build"],
  ["schema-designer", "Schema & Contract Designer", "Build"],
  ["mock-behavior", "Mock Data & Behavior Designer", "Build"],
  ["lab-resources", "Lab Resource Configuration", "Build"],
  ["lab-cockpit", "Development Lab Cockpit", "Build"],
  ["notebook-studio", "Notebook Studio", "Build"],
  ["sql-workspace", "SQL Workspace", "Build"],
  ["pipeline-studio", "Visual Data Pipeline Designer", "Build"],
  ["orchestration", "Orchestration Designer", "Build"],
  ["artifact-preview", "Target Adapter & Artifact Preview", "Build"],
  ["execution-console", "Execution & Validation Console", "Build"],
  ["test-center", "Test & Certification Center", "Build"],
  ["product-catalog", "Data Product Catalog", "Data Products"],
  ["product-builder", "Data Product Builder", "Data Products"],
  ["operations", "Operations Center", "Operate"],
  ["lineage", "Lineage & Dependency Explorer", "Operate"],
  ["contracts", "Contracts & Data Quality", "Govern"],
  ["profiling", "Data Profiling", "Govern"],
  ["repositories", "Corporate Repository Explorer", "Deliver"],
  ["artifact-review", "Artifact Review", "Deliver"],
  ["pr-wizard", "Ready for Review", "Deliver"],
  ["delivery-status", "Delivery Status", "Deliver"],
  ["settings", "Platform & Workspace Settings", "Settings"]
].map(([id, title, module]) => ({ id, title, module }));

export const assets = [
  { id: "customers", name: "customers", fullName: "customer.silver.customers", type: "Table", domain: "Customer", environment: "PROD", owner: "Customer Data", classification: "Internal", rows: 182430, size: "42.8 MB", updated: "12 min ago", description: "Trusted customer profile with lifecycle and consent attributes.", local: false, schema: [["customer_id", "STRING", "NOT NULL", "PK"], ["email", "STRING", "NULL", ""], ["created_at", "TIMESTAMP", "NOT NULL", ""], ["customer_tier", "STRING", "NULL", ""], ["country_code", "STRING", "NULL", ""]], samples: [["C-008421", "maya.chen@example.com", "2026-11-03 08:14:10", "Gold", "US"], ["C-008422", "leo.martin@example.com", "2026-11-03 08:15:02", "Silver", "BR"]] },
  { id: "addresses", name: "customer_addresses", fullName: "customer.silver.customer_addresses", type: "Table", domain: "Customer", environment: "DEV", owner: "Customer Data", classification: "Confidential", rows: 92311, size: "19.2 MB", updated: "1 hour ago", description: "Current and historical customer address records.", local: false, schema: [["address_id", "BIGINT", "NOT NULL", "PK"], ["customer_id", "STRING", "NOT NULL", "FK → customers"], ["city", "STRING", "NULL", ""], ["valid_from", "DATE", "NOT NULL", ""]], samples: [["771902", "C-008421", "Seattle", "2024-04-01"], ["771903", "C-008422", "Campinas", "2025-01-18"]] },
  { id: "orders", name: "orders", fullName: "sales.silver.orders", type: "Table", domain: "Sales", environment: "PROD", owner: "Commerce Analytics", classification: "Internal", rows: 1240891, size: "386 MB", updated: "6 min ago", description: "Order line items from digital and retail channels.", local: false, schema: [["order_id", "STRING", "NOT NULL", "PK"], ["customer_id", "STRING", "NOT NULL", "FK"], ["ordered_at", "TIMESTAMP", "NOT NULL", ""], ["amount", "DECIMAL(12,2)", "NOT NULL", ""], ["status", "STRING", "NOT NULL", ""]], samples: [["O-290184", "C-008421", "2026-11-03 07:45:10", "284.00", "settled"], ["O-290185", "C-008422", "2026-11-03 07:47:52", "59.90", "pending"]] },
  { id: "transactions", name: "transactions", fullName: "sales.gold.transactions", type: "Table", domain: "Sales", environment: "PROD", owner: "Commerce Analytics", classification: "Internal", rows: 4714788, size: "1.8 GB", updated: "3 min ago", description: "Daily transaction facts enriched with customer and channel context.", local: true, localStatus: "Ready", localUpdated: "Today, 09:18", schema: [["transaction_id", "STRING", "NOT NULL", "PK"], ["customer_id", "STRING", "NOT NULL", ""], ["transaction_date", "DATE", "NOT NULL", ""], ["net_amount", "DECIMAL(14,2)", "NOT NULL", ""], ["channel", "STRING", "NULL", ""], ["customer_tier", "STRING", "NULL", ""]], samples: [["T-961108", "C-008421", "2026-11-02", "284.00", "web", "Gold"], ["T-961109", "C-008422", "2026-11-02", "59.90", "store", "Silver"]] },
  { id: "balances", name: "daily_balances", fullName: "finance.gold.daily_balances", type: "Table", domain: "Finance", environment: "PROD", owner: "Finance Data Office", classification: "Restricted", rows: 980220, size: "132 MB", updated: "1 day ago", description: "Account-level daily balance snapshots. Local export requires steward approval.", local: false, exportAllowed: false, schema: [["account_id", "STRING", "NOT NULL", "PK"], ["balance_date", "DATE", "NOT NULL", ""], ["closing_balance", "DECIMAL(16,2)", "NOT NULL", ""], ["currency", "STRING", "NOT NULL", ""]], samples: [["A-008145", "2026-11-02", "10482.41", "USD"], ["A-008146", "2026-11-02", "829.92", "BRL"]] },
  { id: "events", name: "account_events", fullName: "risk.silver.account_events", type: "Kafka topic", domain: "Risk", environment: "DEV", owner: "Risk Engineering", classification: "Internal", rows: 801220, size: "topic · 12 partitions", updated: "Live", description: "Account activity events with event-time and source metadata.", local: false, schema: [["event_id", "STRING", "NOT NULL", "PK"], ["account_id", "STRING", "NOT NULL", ""], ["event_type", "STRING", "NOT NULL", ""], ["event_time", "TIMESTAMP", "NOT NULL", ""], ["risk_score", "DOUBLE", "NULL", ""]], samples: [["E-584201", "A-008145", "payment", "2026-11-03 09:18:32", "0.18"], ["E-584202", "A-008146", "login", "2026-11-03 09:18:46", "0.72"]] },
  { id: "local_customers", name: "customers_seed", fullName: "local.customer.customers_seed", type: "Dataset", domain: "Customer", environment: "LOCAL", owner: "Henrique Silva", classification: "Synthetic", rows: 10000, size: "2.4 MB", updated: "Today, 08:42", description: "Synthetic customer data generated for Customer Ingestion Lab.", local: true, localStatus: "Ready", localUpdated: "Today, 08:42", schema: [["customer_id", "STRING", "NOT NULL", "PK"], ["email", "STRING", "NULL", ""], ["created_at", "TIMESTAMP", "NOT NULL", ""], ["customer_tier", "STRING", "NULL", ""]], samples: [["SYN-00001", "person.1@example.test", "2026-10-29 10:15:00", "Bronze"], ["SYN-00002", "person.2@example.test", "2026-10-29 10:17:00", "Silver"]] },
  { id: "api_customer", name: "customer-profile", fullName: "customer-api.v1.profile", type: "API endpoint", domain: "Customer", environment: "DEV", owner: "Customer Platform", classification: "Internal", rows: 0, size: "REST · v1", updated: "Healthy", description: "Customer profile service for the local integration Lab.", local: false, schema: [["customer_id", "STRING", "required", "path"], ["include_history", "BOOLEAN", "optional", "query"]], samples: [["GET", "/v1/customers/{customer_id}", "200", "Profile response"]] }
];

export const workspaces = [
  { id: "customer-ingestion", name: "Customer Ingestion", domain: "Customer", description: "Build a trusted customer ingest from operational SQL sources.", color: "amber", repository: "data-platform/customer-ingestion", branch: "feature/customer-incremental-load", updated: "14 min ago", labId: "lab-sqlserver", assets: ["customers", "addresses", "local_customers"], pipelineIds: ["customer-pipeline"], notebookIds: ["customer-notebook"], testReadiness: "8 / 9 passing" },
  { id: "streaming-risk", name: "Streaming Risk Events", domain: "Risk", description: "Explore event-time processing, duplicates and late arrivals.", color: "violet", repository: "risk/streaming-events", branch: "feature/late-event-window", updated: "1 hour ago", labId: "lab-kafka", assets: ["events"], pipelineIds: ["risk-pipeline"], notebookIds: ["risk-notebook"], testReadiness: "12 / 12 passing" },
  { id: "customer-360", name: "Customer 360", domain: "Customer", description: "A governed customer view for analytics and activation.", color: "blue", repository: "customer/customer-360", branch: "main", updated: "Yesterday", labId: "lab-multi", assets: ["customers", "addresses", "transactions"], pipelineIds: ["customer-pipeline"], notebookIds: ["customer-notebook"], testReadiness: "Ready for review" },
  { id: "multi-source", name: "Multi-Source Integration", domain: "Operations", description: "Compose Oracle, Kafka, REST and local processing into one Lab.", color: "green", repository: "platform/multi-source-lab", branch: "feature/lab-composition", updated: "2 days ago", labId: "lab-multi", assets: ["orders", "events", "api_customer"], pipelineIds: ["risk-pipeline"], notebookIds: ["risk-notebook"], testReadiness: "6 / 8 passing" }
];

export const pipelineTemplates = [
  { id: "customer-pipeline", name: "customer_incremental_ingest", description: "Incremental SQL ingest with contract validation", status: "Ready", nodes: [{ id: "n1", type: "Source", title: "SQL Server", subtitle: "customer.dbo.Customers", x: 44, y: 90 }, { id: "n2", type: "Extract", title: "Incremental extract", subtitle: "modified_at > checkpoint", x: 275, y: 90 }, { id: "n3", type: "Transform", title: "Normalize profile", subtitle: "6 fields · 2 rules", x: 506, y: 90 }, { id: "n4", type: "Data Quality", title: "Customer contract", subtitle: "8 checks · 1 warning", x: 737, y: 90 }, { id: "n5", type: "Destination", title: "Delta table", subtitle: "customer.silver.customers", x: 968, y: 90 }] },
  { id: "risk-pipeline", name: "risk_event_enrichment", description: "Late-event aware stream enrichment and risk scoring", status: "Warning", nodes: [{ id: "r1", type: "Source", title: "Kafka topic", subtitle: "risk.account_events", x: 70, y: 120 }, { id: "r2", type: "Filter", title: "Valid event envelope", subtitle: "event_id IS NOT NULL", x: 330, y: 120 }, { id: "r3", type: "Transform", title: "Enrich account", subtitle: "join account profile", x: 590, y: 120 }, { id: "r4", type: "Destination", title: "Risk events", subtitle: "risk.silver.account_events", x: 850, y: 120 }] }
];

export const labTemplates = [
  { id: "sqlserver", name: "SQL Server Ingestion", description: "Relational source with incremental change behavior.", tags: ["Database", "Python"], resources: "2 vCPU · 3 GB", components: ["SQL Server", "Python", "Test data generator"] },
  { id: "oracle", name: "Oracle Ingestion", description: "Oracle source with sequence and CDC scenarios.", tags: ["Database", "CDC"], resources: "3 vCPU · 5 GB", components: ["Oracle", "Python", "Metadata service"] },
  { id: "kafka", name: "Kafka Streaming", description: "Event stream with late, duplicate and reordered messages.", tags: ["Streaming", "Spark"], resources: "4 vCPU · 6 GB", components: ["Kafka", "Schema registry", "PySpark"] },
  { id: "api", name: "API Integration", description: "REST endpoints with pagination and failure scenarios.", tags: ["API", "Python"], resources: "2 vCPU · 2 GB", components: ["Mock REST API", "Python", "Monitoring"] },
  { id: "storage", name: "File & Storage", description: "Partitioned files with schema evolution behavior.", tags: ["Storage", "Parquet"], resources: "2 vCPU · 2 GB", components: ["Filesystem", "Parquet", "Test data generator"] },
  { id: "spark", name: "Spark Transformation", description: "A local processing sandbox for PySpark development.", tags: ["Processing", "Notebook"], resources: "4 vCPU · 8 GB", components: ["PySpark", "DuckDB", "Filesystem"] },
  { id: "lakehouse", name: "Lakehouse", description: "Local files, SQL processing and a compact catalog.", tags: ["Delta", "DuckDB"], resources: "4 vCPU · 6 GB", components: ["Delta storage", "DuckDB", "Metadata service"] },
  { id: "multi", name: "Multi-Source Integration", description: "Combine Oracle, Kafka, REST, storage and PySpark.", tags: ["Composable", "5 services"], resources: "6 vCPU · 10 GB", components: ["Oracle", "Kafka", "REST API", "Local storage", "PySpark"] },
  { id: "custom", name: "Custom Lab", description: "Start with a blank topology and choose every component.", tags: ["Custom", "Flexible"], resources: "Configure resources", components: [] }
];

export const componentCatalog = [
  { category: "Databases", items: ["SQL Server", "Oracle", "PostgreSQL", "MySQL", "MongoDB"] },
  { category: "Streaming", items: ["Kafka", "Schema registry", "Event producer"] },
  { category: "APIs", items: ["REST API", "GraphQL API", "Webhook receiver"] },
  { category: "Storage", items: ["Filesystem", "Parquet storage", "S3 compatible", "ADLS compatible"] },
  { category: "Processing", items: ["Python", "DuckDB", "PySpark", "Spark"] },
  { category: "Supporting", items: ["Secrets mock", "Monitoring", "Metadata service", "Test data generator"] }
];

export const pipelineNodeTypes = ["Source", "Extract", "Transform", "Join", "Filter", "Aggregate", "Data Quality", "Conditional Branch", "Destination", "Custom Code", "Notification"];

export const initialState = {
  version: 1,
  activeWorkspace: "customer-ingestion",
  environment: "LOCAL",
  screen: "home",
  activeModule: "home",
  tabs: [{ id: "home", title: "Home", dirty: false, environment: "LOCAL" }],
  selectedAsset: "transactions",
  selectedProduct: "customer-360-product",
  selectedLab: "lab-sqlserver",
  selectedPipeline: "customer-pipeline",
  selectedNotebook: "customer-notebook",
  selectedNode: "n3",
  selectedComponent: null,
  selectedComponents: [],
  componentConnections: [],
  componentSettings: [],
  schemaComponent: "SQL Server",
  selectedTasks: [],
  explorerWidth: 254,
  contextWidth: 330,
  explorerWidthUserSet: false,
  contextWidthUserSet: false,
  explorerCollapsed: false,
  contextCollapsed: false,
  contextTab: "assistant",
  bottomOpen: false,
  bottomTab: "Results",
  search: "",
  globalSearch: "",
  workspaceSearch: "",
  workspaceFilter: "all",
  discoverSearch: "",
  discoverEnvironment: "All",
  discoverDomain: "All",
  labSearch: "",
  labCategory: "All categories",
  productSearch: "",
  productDomain: "All",
  productStatus: "All lifecycle states",
  operationFilter: "All",
  executionFilter: "All",
  repositorySearch: "",
  repositoryProvider: "All providers",
  repositoryDomain: "All domains",
  contractTab: "contract",
  localDeleteTarget: null,
  sqlResult: null,
  pipelineValidation: null,
  theme: "dark",
  favorites: ["transactions", "customers", "customer-pipeline"],
  recentScreens: ["home", "discover", "pipeline-studio"],
  workspaces,
  assets,
  labs: [
    { id: "lab-sqlserver", name: "Customer SQL Server Lab", template: "SQL Server Ingestion", status: "Running", components: ["SQL Server", "Python", "Test data generator"], schemas: ["Customers", "Addresses", "Orders"], endpoints: ["sqlserver.local:1433", "/health"], health: "Healthy", logs: ["09:18:04  SQL Server accepting connections", "09:17:42  Seeded 10,000 synthetic customer rows", "09:17:08  Schema contract loaded · v3"] },
    { id: "lab-kafka", name: "Risk Streaming Lab", template: "Kafka Streaming", status: "Stopped", components: ["Kafka", "Schema registry", "PySpark"], schemas: ["account_events v2"], endpoints: ["kafka.local:9092"], health: "Stopped", logs: ["Yesterday  Lab stopped by Henrique"] },
    { id: "lab-multi", name: "Multi-Source Integration Lab", template: "Multi-Source Integration", status: "Stopped", components: ["Oracle", "Kafka", "REST API", "Local storage", "PySpark"], schemas: ["Accounts", "Risk Events"], endpoints: ["oracle.local:1521", "kafka.local:9092", "api.local:8080"], health: "Stopped", logs: ["Topology saved · 5 components"] }
  ],
  customComponents: ["Oracle", "Kafka", "REST API", "Filesystem", "PySpark"],
  schemas: [{ table: "Customers", fields: [["customer_id", "STRING", "No", "Primary key"], ["email", "STRING", "Yes", "PII · masked"], ["created_at", "TIMESTAMP", "No", "UTC"], ["customer_tier", "STRING", "Yes", "Gold, Silver, Bronze"]] }],
  mockSettings: { rows: 10000, nullPercent: 2, duplicates: 0.4, delay: 120, httpFailure: 0, lateEvents: 3, rate: 1200 },
  mockService: "SQL Server",
  mockProfile: "relational",
  mockSavedAt: "Not saved",
  mockPreview: "No preview run in this session",
  resourceSettings: { cpu: 6, memory: 10, storage: 18, network: "Isolated local network" },
  pipelines: pipelineTemplates,
  orchestration: {
    schedule: "Every day at 02:00 UTC",
    retries: 2,
    timeout: 45,
    concurrency: 2,
    target: "Airflow",
    failure: "Stop downstream tasks",
    tasks: [
      { id: "extract-customers", name: "Extract customers", kind: "Pipeline step" },
      { id: "validate-contract", name: "Validate contract", kind: "On success" },
      { id: "publish-profile", name: "Publish profile", kind: "On success" }
    ],
    edges: [["extract-customers", "validate-contract"], ["validate-contract", "publish-profile"]]
  },
  notebooks: [
    { id: "customer-notebook", name: "customer_profile_quality.ipynb", runtime: "Python Local", cells: [
      { id: "c1", type: "markdown", source: "# Customer profile quality\nExplore the synthetic customer seed and validate profile coverage.", output: null },
      { id: "c2", type: "sql", source: "SELECT customer_tier, COUNT(*) AS customers\nFROM local.customer.customers_seed\nGROUP BY customer_tier\nORDER BY customers DESC", output: null },
      { id: "c3", type: "python", source: "quality_rate = 0.982\nprint(f'Profile completeness: {quality_rate:.1%}')", output: null }
    ] },
    { id: "risk-notebook", name: "late_event_analysis.ipynb", runtime: "PySpark Local", cells: [{ id: "r-c1", type: "markdown", source: "# Late event analysis\nReview the event-time distribution in the Risk Lab.", output: null }, { id: "r-c2", type: "python", source: "late_event_rate = 0.034\nprint(f'Late events: {late_event_rate:.1%}')", output: null }] }
  ],
  sql: { text: "SELECT channel, COUNT(*) AS transactions, SUM(net_amount) AS revenue\nFROM sales.gold.transactions\nGROUP BY channel\nORDER BY revenue DESC", route: "AUTO", history: ["SELECT COUNT(*) FROM sales.gold.transactions", "SELECT * FROM customer.silver.customers LIMIT 20"] },
  products: [
    { id: "customer-360-product", name: "Customer 360", domain: "Customer", owner: "Customer Data Office", status: "Draft", description: "A trusted, consent-aware customer profile for analytics and activation.", assets: ["customers", "addresses"], pipelines: ["customer-pipeline"], contracts: ["customer-profile-v3"], ports: ["customer_profile_v1"], consumers: ["Growth Analytics", "Support Insights"], slo: "99.5% daily freshness", quality: "1 warning" },
    { id: "risk-event-product", name: "Risk Event Stream", domain: "Risk", owner: "Risk Engineering", status: "Published", description: "Governed account activity events enriched with event-time risk signals.", assets: ["events"], pipelines: ["risk-pipeline"], contracts: ["account-event-v2"], ports: ["risk_events_v2"], consumers: ["Fraud Operations", "Risk Analytics"], slo: "99.0% 5-minute freshness", quality: "Healthy" }
  ],
  operations: [
    { id: "op-mat-1", type: "Materialization", target: "sales.gold.transactions", state: "Transferring", progress: 68, phase: "Downloading Parquet chunks", rows: "3.2M / 4.7M rows", bytes: "1.2 / 1.8 GB", started: "4 min ago", logs: ["09:18:02  Chunk 18 verified", "09:17:40  3,204,810 rows transferred", "09:14:08  Statement result ready"] },
    { id: "op-pipe-1", type: "Pipeline run", target: "customer_incremental_ingest", state: "Failed", progress: 72, phase: "Contract validation", error: "Required column customer_tier was missing from the source schema.", started: "18 min ago", logs: ["09:04:10  SQL Server source connected", "09:04:18  2,842 rows extracted", "09:04:21  Transform completed", "09:04:22  Contract failed: customer_tier missing"] },
    { id: "op-lab-1", type: "Lab lifecycle", target: "Customer SQL Server Lab", state: "Completed", progress: 100, phase: "Ready", started: "Today, 09:17", logs: ["Services healthy · 3 endpoints ready"] }
  ],
  tests: [{ name: "Customer contract · required fields", category: "Contract", state: "Passed", duration: "0.8s" }, { name: "Customer contract · source compatibility", category: "Schema", state: "Failed", duration: "0.4s", detail: "customer_tier missing" }, { name: "Incremental checkpoint replay", category: "Integration", state: "Passed", duration: "2.4s" }, { name: "Duplicate customer key", category: "Data Quality", state: "Passed", duration: "1.1s" }, { name: "Null consent preference", category: "Unit", state: "Passed", duration: "0.3s" }, { name: "Local runtime portability", category: "Runtime Compatibility", state: "Warning", duration: "0.6s", detail: "PySpark transform requires adapter review" }],
  repositories: [
    { id: "repo-customer", name: "customer-ingestion", path: "data-platform/customer-ingestion", provider: "GitHub Enterprise", domain: "Customer", owner: "Data Platform", technology: "Python · SQL · Airflow", branch: "main", access: "Write", updated: "12 min ago", files: ["README.md", "pipelines/customer_ingest.py", "contracts/customer_profile.yaml", "tests/test_customer_ingest.py", "notebooks/customer_profile_quality.ipynb", "orchestration/customer_ingest_dag.py"] },
    { id: "repo-risk", name: "streaming-events", path: "risk/streaming-events", provider: "GitLab", domain: "Risk", owner: "Risk Engineering", technology: "PySpark · Kafka", branch: "main", access: "Write", updated: "1 hour ago", files: ["README.md", "src/risk_events.py", "schemas/account_event.avsc", "tests/test_risk_events.py"] },
    { id: "repo-finance", name: "finance-balance-service", path: "finance/balance-service", provider: "GitHub Enterprise", domain: "Finance", owner: "Finance Data Office", technology: "Databricks · SQL", branch: "main", access: "Restricted", updated: "Yesterday", files: ["README.md", "src/balance.sql", "contracts/balance.yaml"] }
  ],
  selectedRepository: "repo-customer",
  selectedFiles: ["pipelines/customer_ingest.py", "contracts/customer_profile.yaml", "tests/test_customer_ingest.py"],
  prs: [{ number: 284, title: "Add customer profile incremental ingest", repository: "customer-ingestion", branch: "feature/customer-incremental-load", state: "Checks Running", checks: "2 / 3", created: "Today, 09:05", workspace: "Customer Ingestion" }],
  delivery: { stage: 1, title: "Add customer profile pipeline", description: "Adds the incremental profile pipeline, contract and validation tests." },
  chat: [{ role: "assistant", text: "Welcome to Dexter. I can work with the assets and editor context you choose to share. What are you building today?", time: "09:02" }],
  chatContext: [],
  pendingSuggestion: null,
  notifications: [{ title: "Pipeline validation needs attention", detail: "customer_incremental_ingest · customer_tier is missing", time: "18 min ago", unread: true }, { title: "Materialization in progress", detail: "sales.gold.transactions · 68% complete", time: "4 min ago", unread: true }],
  testReadiness: false,
  movementStep: 1,
  movementConfig: { mode: "Full table", columns: ["transaction_id", "customer_id", "transaction_date", "net_amount", "channel", "customer_tier"], format: "Parquet", destination: "Local workspace" },
  compareAssets: ["customers", "addresses"],
  syntheticConfig: { rows: 25000, source: "customers", destination: "Local workspace" },
  syntheticOptions: ["Preserve PK/FK relationships", "PII-safe values"],
  mockScenarios: ["Schema drift"],
  mockBehaviors: {},
  productDraft: { name: "", purpose: "", domain: "Customer", owner: "Henrique Silva", selectedAssets: ["customers"], selectedPipelines: ["customer-pipeline"], selectedContracts: ["customer-profile-v3"], port: "customer_profile_v1", slo: "99.5% daily freshness" },
  adapter: "Airflow",
  profileAsset: "transactions",
  modal: null
};

export function freshState() {
  const state = structuredClone(initialState);
  for (const pipeline of state.pipelines) {
    pipeline.edges ??= pipeline.nodes.slice(1).map((node, index) => [pipeline.nodes[index].id, node.id]);
  }
  return state;
}
