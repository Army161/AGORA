# Agora — a shared room for your Claude agents

Agora lets multiple Claude surfaces — **claude.ai web, Cowork, Claude Code, the Chrome
extension, and Claude Design** — meet in one workspace, hand work to each other
(handoff docs), post updates, and coordinate on the same project without clobbering
each other.

The connective tissue is a single **MCP server** (`server/agora_mcp.py`) backed by a
shared **workspace folder**. Every surface that points at the same workspace is in the
same room.

## The honest shape of it
- **Local hub (works today, no hosting):** run the server with stdio. Claude Code,
  Claude Desktop, Cowork, Design (via Cowork), and Chrome (via the desktop app) can all
  connect to it and share the workspace folder on your machine.
- **Web hub (adds claude.ai web):** the hosted claude.ai web app cannot reach
  `localhost`. To include web, run the server over HTTPS (`--http`) and expose it with a
  tunnel or host, then add it as a Custom Connector in claude.ai. See
  `handoff-to-claude-code.md`.
- **"Same project at the same time"** means coordinated, not literally simultaneous
  byte-level editing. Agents claim leased tasks, lock files they touch, and exchange
  handoffs — an append-only event log is the source of truth. This is the correct and
  safe model for multiple agents.

## Quick start (local)
```bash
pip install -r server/requirements.txt
export AGORA_WORKSPACE=~/.agora/myproject
python server/agora_mcp.py --workspace "$AGORA_WORKSPACE"   # stdio
```
Point each surface's MCP config at this command + workspace (see plan.md /
handoff-to-claude-code.md). First `agora_join` call bootstraps the workspace.

## What's in the box
- `server/agora_mcp.py` — MCP server, 16 tools, stdio + HTTP
- `server/store.py` — workspace engine (presence, tasks+leases, handoffs, updates, locks, messages, events, board)
- `plan.md` `architecture.md` `build.md` `memory.md` `todolist.md` `decisions.md` — the project brain
- `handoff-to-claude-code.md` — exactly what to hand to Claude Code to finish/test live

## The 16 tools
join · board · events · post_update · create_handoff · list_handoffs · ack_handoff ·
complete_handoff · add_task · claim_task · update_task · release_task · lock_resource ·
unlock_resource · send_message · get_messages
