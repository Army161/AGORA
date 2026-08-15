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
- **claude.ai web / Design / Chrome**: these attach as a Custom Connector over HTTPS and
  authenticate via real OAuth 2.1 (Dynamic Client Registration + PKCE) — a pasted bearer
  token isn't enough, since the connector self-registers and redirects the browser through
  an authorization flow. Use `start-web-connector.sh` / `.ps1`, which runs
  `agora_mcp.py --http --oauth --public-url ...` and implements that flow. See
  `CONNECT.md` §3–5 for the exact tunnel-first steps.

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
