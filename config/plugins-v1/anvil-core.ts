import { spawn } from "node:child_process"
import { fileURLToPath } from "node:url"
import { tool } from "@opencode-ai/plugin"

const memoryHelper = fileURLToPath(new URL("../scripts/memory.py", import.meta.url))
const analyticsHelper = fileURLToPath(new URL("../scripts/analytics/tool_cli.py", import.meta.url))
const configRoot = fileURLToPath(new URL("..", import.meta.url))
const MAX_OUTPUT = 60_000

function runHelper(script: string, args: string[], input?: object): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn("python3", [script, ...args], {
      cwd: configRoot,
      stdio: [input ? "pipe" : "ignore", "pipe", "pipe"],
      env: { ...process.env, PYTHONPATH: configRoot },
    })
    let stdout = ""
    let stderr = ""
    let oversized = false
    const timeout = setTimeout(() => child.kill("SIGTERM"), 300_000)
    child.stdout.setEncoding("utf8").on("data", (part: string) => {
      stdout += part
      if (stdout.length > MAX_OUTPUT) {
        oversized = true
        child.kill("SIGTERM")
      }
    })
    child.stderr.setEncoding("utf8").on("data", (part: string) => {
      stderr = (stderr + part).slice(-4_000)
    })
    child.once("error", (error) => {
      clearTimeout(timeout)
      reject(error)
    })
    child.once("close", (code) => {
      clearTimeout(timeout)
      if (oversized) reject(new Error("Anvil tool output exceeded its 60 KiB limit"))
      else if (code !== 0) reject(new Error(stderr.trim() || `Anvil helper exited with ${code}`))
      else resolve(stdout.trim() || "{}")
    })
    if (input) child.stdin.end(JSON.stringify(input))
  })
}

const str = (max: number, min = 0) => tool.schema.string().min(min).max(max)
const optionalStr = (max: number) => str(max).optional()
const int = (minimum: number, maximum: number) => tool.schema.number().int().min(minimum).max(maximum)

const analyticsDefinitions = {
  anvil_analytics_search_catalog: {
    action: "search_catalog", description: "Search cached Unity Catalog metadata without calling an LLM or Databricks.",
    args: { query: str(256, 1), parent: optionalStr(768) },
  },
  anvil_analytics_describe_table: {
    action: "describe_table", description: "Read cached table metadata and hydrate its schema through Anvil's shared Databricks capability.",
    args: { full_name: str(1024, 1) },
  },
  anvil_analytics_preview_table: {
    action: "preview_table", description: "Run a user-requested table preview capped at 100 rows.",
    args: { full_name: str(1024, 1), warehouse_id: str(256, 1), limit: int(1, 100).optional() },
  },
  anvil_analytics_run_query: {
    action: "run_query", description: "Run bounded read-only SQL through the AUTO, LOCAL or DATABRICKS query router.",
    args: { sql: str(64_000, 1), route: optionalStr(16), warehouse_id: optionalStr(256) },
  },
  anvil_analytics_explain_query: {
    action: "explain_query", description: "Explain whether read-only SQL can use exact local snapshot coverage.",
    args: { sql: str(64_000, 1) },
  },
  anvil_analytics_local_coverage: {
    action: "get_local_coverage", description: "Check exact validated local snapshot coverage for one table or query.",
    args: { full_name: str(1024, 1), sql: optionalStr(64_000) },
  },
  anvil_analytics_materialize: {
    action: "materialize", description: "Start bounded resumable Parquet materialization for selected columns. Confirm only when the user explicitly approves a full-table copy.",
    args: {
      source_name: str(1024, 1),
      columns: tool.schema.array(str(256, 1)).min(1).max(100),
      predicate: optionalStr(16_000), warehouse_id: str(256, 1),
      max_rows: int(1, 1_000_000).optional(), max_bytes: int(1_048_576, 1_073_741_824).optional(),
      full_table_confirmed: tool.schema.boolean().optional(), force_refresh: tool.schema.boolean().optional(),
    },
  },
  anvil_analytics_refresh_metadata: {
    action: "refresh_metadata", description: "Refresh cached catalogs, schemas or tables through the shared Databricks capability.",
    args: { scope: optionalStr(16), catalog_name: optionalStr(255), schema_name: optionalStr(255) },
  },
  anvil_analytics_refresh_local: {
    action: "refresh_local", description: "Resume a previously started local materialization by its operation identifier.",
    args: { operation_id: str(128, 1) },
  },
  anvil_analytics_profile_table: {
    action: "profile_table", description: "Summarize a preview of at most 100 rows without returning raw sample rows.",
    args: { full_name: str(1024, 1), warehouse_id: str(256, 1), limit: int(1, 100).optional() },
  },
  anvil_analytics_lineage: {
    action: "get_lineage", description: "Read at most 100 Unity Catalog table-lineage records.",
    args: { full_name: str(1024, 1), warehouse_id: str(256, 1), limit: int(1, 100).optional() },
  },
  anvil_analytics_query_history: {
    action: "get_query_history", description: "Read recent local Analytics query history with a bounded record count.",
    args: { limit: int(1, 100).optional() },
  },
  anvil_analytics_compare_routes: {
    action: "compare_remote_local", description: "Compare bounded query results from an exact local snapshot and Databricks.",
    args: { sql: str(64_000, 1), warehouse_id: str(256, 1) },
  },
}

const analyticsTools = Object.fromEntries(Object.entries(analyticsDefinitions).map(([name, definition]) => [
  name,
  tool({
    description: definition.description,
    args: definition.args,
    async execute(args: Record<string, unknown>) {
      return runHelper(analyticsHelper, ["--tool", definition.action], args)
    },
  }),
]))

export const AnvilCorePlugin = async () => ({
  tool: {
    anvil_memory_search: tool({
      description: "Search Anvil's Markdown memory with bounded lexical matching. This tool never writes memory.",
      args: { query: str(500, 1), scope: optionalStr(100), limit: int(1, 5).optional() },
      async execute(args: { query: string; scope?: string; limit?: number }) {
        const argv = ["tool-search", args.query, "--limit", String(args.limit ?? 5)]
        if (args.scope) argv.push("--scope", args.scope)
        return runHelper(memoryHelper, argv)
      },
    }),
    ...analyticsTools,
  },
})
