import { spawn } from "node:child_process"
import { fileURLToPath } from "node:url"
import { Plugin } from "@opencode/plugin"

type SearchInput = { query: string; scope?: string; limit?: number }

const memoryHelper = fileURLToPath(new URL("../../scripts/memory.py", import.meta.url))

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
    })
  },
})
