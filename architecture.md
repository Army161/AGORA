# Architecture — Agora

## Layers
1. **Surfaces** (clients): claude.ai web, Cowork, Claude Code, Chrome ext, Design.
2. **Access**: MCP (stdio for local surfaces; streamable-HTTP for web). Claude Code also
   bundles it as a plugin.
3. **Server** (`agora_mcp.py`): 16 MCP tools, thin wrappers over the store.
4. **Engine** (`store.py`): all logic, no MCP dependency, unit-testable.
5. **Workspace** (folder): the shared state, readable by humans.

## Workspace layout (`$AGORA_WORKSPACE`)
```
meta.json        counters + workspace info
agents.json      presence registry (surface, role, last_seen, current)
tasks.json       tasks with status + owner + lease_until
locks.json       resource locks with holder + lease
events.jsonl     append-only event log (source of truth, seq-numbered)
board.md         rendered human-readable snapshot (regenerated each write)
AGENTS.md        operating manual for agents
updates/UPDATES.md + index.json   the updates feed
handoffs/H-XXXX.md + index.json   one doc per handoff
messages/index.json               direct/broadcast messages
.lock/           transient mutex dir
```

## Concurrency
- One mutex (atomic `mkdir` lock dir, stale-broken after 30s, 10s acquire timeout)
  guards each mutation: read → modify → write (atomic temp+replace) → append event →
  render board → release.
- Tasks/locks use **leases** (TTL). A crashed agent's claim expires automatically.
- `force=true` overrides a live lease when a human decides to.

## Catch-up model
`agora_join` returns a summary; `agora_events(since_seq)` returns only what's new. This
keeps multi-agent context cheap.
