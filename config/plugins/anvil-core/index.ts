import { spawn } from "node:child_process"
import { fileURLToPath } from "node:url"
import { Plugin } from "@opencode/plugin"

type SearchInput = { query: string; scope?: string; limit?: number }
type AnalyticsInput = Record<string, unknown>

const memoryHelper = fileURLToPath(new URL("../../scripts/memory.py", import.meta.url))
const analyticsHelper = fileURLToPath(new URL("../../scripts/analytics/tool_cli.py", import.meta.url))
const configRoot = fileURLToPath(new URL("../..", import.meta.url))

function searchMemory(input: SearchInput, signal: AbortSignal): Promise<string> {
  const args = [memoryHelper, "tool-search", input.query, "--limit", String(input.limit ?? 5)]
  if (input.scope) args.push("--scope", input.scope)
  return new Promise((resolve, reject) => {
    const child = spawn("python3", args, { stdio: ["ignore", "pipe", "pipe"], signal })
    let stdout = ""
    let stderr = ""
    child.stdout.setEncoding("utf8").on("data", (part: string) => { stdout += part })
    child.stderr.setEncoding("utf8").on("data", (part: string) => { stderr += part })
    child.once("error", reject)
    child.once("close", (code) => {
      if (code !== 0) reject(new Error(stderr.trim() || `memory search exited with ${code}`))
      else resolve(stdout.trim() || '{"results":[]}')
    })
  })
}

function runAnalyticsTool(name: string, input: AnalyticsInput, signal: AbortSignal): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn("python3", [analyticsHelper, "--tool", name], {
      cwd: configRoot,
      stdio: ["pipe", "pipe", "pipe"],
      signal,
      env: { ...process.env, PYTHONPATH: configRoot },
    })
    let stdout = ""
    let stderr = ""
    child.stdout.setEncoding("utf8").on("data", (part: string) => {
      stdout += part
      if (stdout.length > 60_000) child.kill("SIGTERM")
    })
    child.stderr.setEncoding("utf8").on("data", (part: string) => {
      stderr = (stderr + part).slice(-4_000)
    })
    child.once("error", reject)
    child.once("close", (code) => {
      if (code !== 0) reject(new Error(stderr.trim() || `Analytics action exited with ${code}`))
      else resolve(stdout.trim() || "{}")
    })
    child.stdin.end(JSON.stringify(input))
  })
}

const analyticsTools = [
  { name: "anvil_analytics_search_catalog", action: "search_catalog",
    description: "Search cached Unity Catalog metadata across catalogs, schemas, tables and views. This is local-cache search and does not call an LLM or Databricks.",
    input: { type: "object", properties: { query: { type: "string", minLength: 1, maxLength: 256 }, parent: { type: "string", maxLength: 768 } }, required: ["query"], additionalProperties: false } },
  { name: "anvil_analytics_describe_table", action: "describe_table",
    description: "Read cached table metadata and hydrate its schema when needed, using Anvil's shared Databricks capability.",
    input: { type: "object", properties: { full_name: { type: "string", minLength: 1, maxLength: 1024 } }, required: ["full_name"], additionalProperties: false } },
  { name: "anvil_analytics_preview_table", action: "preview_table",
    description: "Run a user-requested preview capped at 100 rows from a selected running SQL warehouse.",
    input: { type: "object", properties: { full_name: { type: "string", minLength: 1, maxLength: 1024 }, warehouse_id: { type: "string", minLength: 1, maxLength: 256 }, limit: { type: "integer", minimum: 1, maximum: 100, default: 20 } }, required: ["full_name", "warehouse_id"], additionalProperties: false } },
  { name: "anvil_analytics_run_query", action: "run_query",
    description: "Run a bounded read-only SQL query through Anvil's AUTO, LOCAL or DATABRICKS query router. Local SQL requires proven snapshot coverage; remote SQL requires a running warehouse.",
    input: { type: "object", properties: { sql: { type: "string", minLength: 1, maxLength: 64000 }, route: { type: "string", enum: ["AUTO", "LOCAL", "DATABRICKS"], default: "AUTO" }, warehouse_id: { type: "string", maxLength: 256 } }, required: ["sql"], additionalProperties: false } },
  { name: "anvil_analytics_explain_query", action: "explain_query",
    description: "Explain whether a read-only query can use the exact local snapshot or must use Databricks.",
    input: { type: "object", properties: { sql: { type: "string", minLength: 1, maxLength: 64000 } }, required: ["sql"], additionalProperties: false } },
  { name: "anvil_analytics_local_coverage", action: "get_local_coverage",
    description: "Check whether a table or read-only query is fully covered by a validated local snapshot.",
    input: { type: "object", properties: { full_name: { type: "string", minLength: 1, maxLength: 1024 }, sql: { type: "string", maxLength: 64000 } }, required: ["full_name"], additionalProperties: false } },
  { name: "anvil_analytics_materialize", action: "materialize",
    description: "Start a bounded, resumable local Parquet materialization for explicitly selected columns and filters. Set full_table_confirmed only when the user explicitly confirms a full-table copy.",
    input: { type: "object", properties: { source_name: { type: "string", minLength: 1, maxLength: 1024 }, columns: { type: "array", minItems: 1, maxItems: 100, items: { type: "string" } }, predicate: { type: "string", maxLength: 16000 }, warehouse_id: { type: "string", minLength: 1, maxLength: 256 }, max_rows: { type: "integer", minimum: 1, maximum: 1000000, default: 100000 }, max_bytes: { type: "integer", minimum: 1048576, maximum: 1073741824, default: 536870912 }, full_table_confirmed: { type: "boolean", default: false }, force_refresh: { type: "boolean", default: false } }, required: ["source_name", "columns", "warehouse_id"], additionalProperties: false } },
  { name: "anvil_analytics_refresh_metadata", action: "refresh_metadata",
    description: "Refresh cached catalogs, schemas or tables through the shared Databricks capability.",
    input: { type: "object", properties: { scope: { type: "string", enum: ["catalogs", "schemas", "tables"] }, catalog_name: { type: "string", maxLength: 255 }, schema_name: { type: "string", maxLength: 255 } }, additionalProperties: false } },
  { name: "anvil_analytics_refresh_local", action: "refresh_local",
    description: "Resume or refresh a previously started local materialization by its operation identifier.",
    input: { type: "object", properties: { operation_id: { type: "string", minLength: 1, maxLength: 128 } }, required: ["operation_id"], additionalProperties: false } },
  { name: "anvil_analytics_profile_table", action: "profile_table",
    description: "Compute a small descriptive profile from a user-requested preview of at most 100 rows; raw sample rows are not included in the profile response.",
    input: { type: "object", properties: { full_name: { type: "string", minLength: 1, maxLength: 1024 }, warehouse_id: { type: "string", minLength: 1, maxLength: 256 }, limit: { type: "integer", minimum: 1, maximum: 100, default: 100 } }, required: ["full_name", "warehouse_id"], additionalProperties: false } },
  { name: "anvil_analytics_lineage", action: "get_lineage",
    description: "Read at most 100 Unity Catalog table-lineage records from the documented system.access.table_lineage system table.",
    input: { type: "object", properties: { full_name: { type: "string", minLength: 1, maxLength: 1024 }, warehouse_id: { type: "string", minLength: 1, maxLength: 256 }, limit: { type: "integer", minimum: 1, maximum: 100, default: 100 } }, required: ["full_name", "warehouse_id"], additionalProperties: false } },
  { name: "anvil_analytics_query_history", action: "get_query_history",
    description: "Read recent local Analytics query history with bounded record count.",
    input: { type: "object", properties: { limit: { type: "integer", minimum: 1, maximum: 100, default: 20 } }, additionalProperties: false } },
  { name: "anvil_analytics_compare_routes", action: "compare_remote_local",
    description: "Compare bounded results for the same read-only query on a covered local snapshot and Databricks. Reports equality only when both complete bounded results are available.",
    input: { type: "object", properties: { sql: { type: "string", minLength: 1, maxLength: 64000 }, warehouse_id: { type: "string", minLength: 1, maxLength: 256 } }, required: ["sql", "warehouse_id"], additionalProperties: false } },
]

export default Plugin.define({
  id: "anvil-core",
  async setup(ctx) {
    await ctx.tool.transform((editor) => {
      editor.add({
        name: "anvil_memory_search",
        description: "Search Anvil's Markdown memory with bounded lexical matching. This tool never writes memory.",
        input: {
          type: "object",
          properties: {
            query: { type: "string", minLength: 1, maxLength: 500 },
            scope: { type: "string", maxLength: 100 },
            limit: { type: "integer", minimum: 1, maximum: 5, default: 5 },
          },
          required: ["query"],
          additionalProperties: false,
        },
        execute: async (raw, context) => {
          const input = raw as SearchInput
          const content = await searchMemory(input, context.signal)
          return { content }
        },
      })
      for (const definition of analyticsTools) {
        editor.add({
          name: definition.name,
          description: definition.description,
          input: definition.input,
          execute: async (raw, context) => ({
            content: await runAnalyticsTool(definition.action, raw as AnalyticsInput, context.signal),
          }),
        })
      }
    })
  },
})
