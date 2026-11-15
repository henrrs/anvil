import { spawn } from "node:child_process"
import { fileURLToPath } from "node:url"
import { tool } from "@opencode-ai/plugin"

const memoryHelper = fileURLToPath(new URL("../scripts/memory.py", import.meta.url))
const configRoot = fileURLToPath(new URL("..", import.meta.url))
const MAX_OUTPUT = 60_000

function runHelper(script: string, args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn("python3", [script, ...args], {
      cwd: configRoot,
      stdio: ["ignore", "pipe", "pipe"],
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
  })
}

const str = (max: number, min = 0) => tool.schema.string().min(min).max(max)
const int = (minimum: number, maximum: number) => tool.schema.number().int().min(minimum).max(maximum)

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
  },
})
