# Agora — Claude Code plugin

Bundles the Agora MCP server and auto-wires it into Claude Code, plus slash commands, a
coordination skill, and a coordinator subagent.

## Install (local marketplace)
1. `pip install -r server/requirements.txt` (needs python3 + mcp + pydantic)
2. Add this plugin to Claude Code (plugin marketplace pointing at this folder, or copy
   into your plugins dir). On session start, `.mcp.json` launches the server with the
   shared workspace `~/.agora/main` (the server expands `~`) — no editing needed. To use a
   different room, change `env.AGORA_WORKSPACE` in `.mcp.json`.
3. Verify: run `/agora-board`. First call bootstraps `~/.agora/main/`.

## Commands
- `/agora-join [id] [role]` — enter the room, get caught up
- `/agora-board` — see agents, tasks, locks, handoffs
- `/agora-take [task] [id]` — claim a task (leased) then work it
- `/agora-update [id] [msg]` — post progress
- `/agora-handoff [from] [to|any] [title]` — hand work off with a full doc

## Notes
- All surfaces must use the SAME workspace path to share a room. For other surfaces, see
  the top-level `handoff-to-claude-code.md`.
- The bundled skill `agora-coordination` tells any agent the safe protocol automatically.
