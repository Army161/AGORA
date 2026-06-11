# Plan — Agora

## Goal
One shared workspace where 5 Claude surfaces (claude.ai, Cowork, Claude Code, Chrome,
Design) meet, exchange handoff/update docs, and co-work a project safely. Plus a
mirrored MCP/skill so the same capability is available from chat surfaces.

## Strategy (why this shape)
MCP is the only interoperability layer common to all five surfaces. So the product =
one MCP server + one shared workspace folder + coordination conventions, packaged two
ways: (a) a Claude Code **plugin** (auto-wires the server), and (b) a standalone
**skill** for chat surfaces. Both talk to the same server, so they mirror each other.

## Phases
1. **Core engine** — workspace store + MCP server. [DONE]
2. **Claude Code plugin** — plugin.json, .mcp.json, commands, bundled skill, agent. [NEXT]
3. **Standalone skill** — SKILL.md + tiny client so claude.ai/Cowork use the same room. [NEXT]
4. **Per-surface connect guides** — exact config for all 5 surfaces. [PARTIAL in README]
5. **Web dashboard (optional)** — static page rendering board.md/events for humans. [LATER]
6. **Web hub deploy** — HTTPS + tunnel/host + claude.ai custom connector. [HANDOFF]
7. **Live cross-surface test** — needs real apps/accounts. [HANDOFF to Claude Code]

## Design rules
- Token-frugal: tools return compact JSON; board.md is the human view; agents poll
  `agora_events(since_seq)` to catch up cheaply instead of re-reading everything.
- Safety: leases auto-expire (no permanent deadlock), locks prevent clobbering,
  event log is append-only truth.
- Portable: stdlib-only engine; server needs only mcp + pydantic.
