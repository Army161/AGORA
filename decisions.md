# Decisions (ADR-style) — Agora

## D1: MCP server as the interoperability layer
All 5 surfaces can speak MCP; nothing else is common to all. Rejected: a custom webapp
(web can't drive the other agents), shared-folder-only (web/Chrome/Design can't reliably
use a local folder). MCP wins.

## D2: Shared workspace folder as state
Human-readable, git-friendly, zero infra, swappable later for a DB/vector store. Matches
the user's markdown-brain vision (CLAUDE.md/MEMORY.md/handoffs).

## D3: Leases + locks + event log (not real-time co-editing)
Safe multi-agent coordination. Leases auto-expire so a dead agent never deadlocks the
room. Event log (append-only, seq'd) is the source of truth and enables cheap catch-up.

## D4: stdlib-only engine, MCP-free
`store.py` has no third-party deps so it is trivially testable and portable; the server
is a thin shell. Server deps limited to mcp + pydantic.

## D5: Ship as plugin AND skill
Plugin auto-wires Claude Code; skill covers chat surfaces. Both hit the same server, so
they mirror by construction (satisfies "MCP/skill that mirrors the plugin app").
