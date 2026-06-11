# Handoff to Claude Code — finish, install, test live

This repo contains a tested core (Phase 1). The items below need a real machine, real
app configs, and accounts — ideal for Claude Code running locally.

## 1. Wire each surface to the server (same workspace for all)
Run once locally:
```bash
pip install -r server/requirements.txt
export AGORA_WORKSPACE=~/.agora/myproject
```
- **Claude Code**: add to `.mcp.json` (or use the plugin once Phase 2 lands):
  ```json
  {"mcpServers":{"agora":{"command":"python","args":["ABS/PATH/server/agora_mcp.py","--workspace","~/.agora/myproject"]}}}
  ```
- **Claude Desktop / Cowork**: add the same server to the desktop MCP config. Design and
  Chrome inherit MCP tools when run through the desktop app.
- **claude.ai web**: requires HTTPS. Run `python server/agora_mcp.py --http --port 8848`
  then expose it (e.g. a tunnel) and register the public URL as a Custom Connector in
  claude.ai settings. Verify the docs at https://support.claude.com for the current
  connector steps before configuring.

## 2. Build remaining phases (or let this Claude session continue them)
- Phase 2 plugin, Phase 3 skill, Phase 4 guides, Phase 5 dashboard (specs in plan.md / todolist.md).

## 3. Live acceptance test
With ≥2 surfaces connected to the same workspace:
1. Surface A: `agora_join` → `agora_add_task` → `agora_claim_task`.
2. Surface B: `agora_join` → `agora_board` (sees A + task) → tries to claim same task
   (should be refused) → `agora_create_handoff` to A.
3. Surface A: `agora_list_handoffs` → `agora_ack_handoff` → `agora_complete_handoff`.
4. Confirm `board.md`, `updates/UPDATES.md`, `handoffs/*.md` reflect all of it.

## Known limits to verify on real apps
- Exact MCP config path/format per app (changes over time — check current docs).
- Whether Chrome/Design expose third-party MCP tools in your build.
- HTTPS/auth hardening before exposing the server publicly (add a token/header).
