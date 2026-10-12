# ADR-0004: Zero Anvil MCP servers by default

**Status:** Accepted

## Decision

The Anvil-managed global config declares no MCP servers and denies unlisted tool capabilities to the Anvil agent.

## Context

MCP tools add prompt/tool surface, credentials, network behavior, and external capabilities. V1 does not need them to provide its core coding harness. Repository or organization-owned MCP configuration must remain under its owner's control.

## Consequences

Reforge removes old global MCP definitions from the active global config and backs them up. It does not erase project/system/remote definitions; doctor warns about visible project configuration. The agent's default-deny policy prevents arbitrary discovered tools from becoming Anvil capabilities.
