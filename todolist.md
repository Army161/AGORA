# To-do — Agora

## Phase 1 — Core engine
- [x] Decide architecture (MCP spine + workspace + conventions)
- [x] Workspace engine `store.py` (presence, tasks/leases, handoffs, updates, locks, messages, events, board)
- [x] MCP server `agora_mcp.py` (16 tools, stdio + HTTP)
- [x] requirements.txt
- [x] Compile + --help + end-to-end smoke test
- [x] Brain docs (plan/build/memory/architecture/decisions/todolist/README)

## Phase 2 — Claude Code plugin
- [x] `plugin/.claude-plugin/plugin.json`
- [x] `plugin/.mcp.json` (wire server via ${CLAUDE_PLUGIN_ROOT}, vendored server/)
- [x] Commands: /agora-join, /agora-board, /agora-take, /agora-update, /agora-handoff
- [x] Bundled skill `skills/agora-coordination/SKILL.md`
- [x] Coordinator agent `agents/agora-coordinator.md`
- [x] Plugin README + install steps

## Phase 3 — Standalone skill (chat surfaces)
- [x] `skill/agora/SKILL.md` mirroring plugin conventions
- [x] Connect + protocol instructions for claude.ai + Cowork (in SKILL.md)

## Phase 4 — Per-surface connect guides
- [x] Claude Code  [x] Cowork/Desktop  [x] Design  [x] Chrome  [x] claude.ai web (guide; live wiring = Phase 6) — see CONNECT.md

## Phase 5 — Web dashboard (optional)
- [x] `dashboard/index.html` — flagship cockpit (sidebar, KPIs, multi-pane workspace, task queue + routing, threads, shared memory + house style, exec log, settings, palette, dark/light, keyboard, skeletons, empty/error states). See dashboard/DASHBOARD.md

## Phase 6 — Web hub deploy (HANDOFF)
- [x] Live bridge server/bridge.py (GET /state, POST /act, serves dashboard; tested) + dashboard auto-connects
- [x] Shared memory in engine + 3 MCP tools (pin_fact, set_house_style, get_memory) — 19 tools total
- [x] HANDOFF.md written for Claude Code
- [x] Bearer-token auth added to bridge.py (--token / AGORA_TOKEN; /state + /act gated)
- [x] Bearer-token auth added to agora_mcp.py HTTP mode (--token; Starlette middleware)
- [x] Constant-time compare (hmac.compare_digest) in bridge.py + agora_mcp.py + vendored copies
- [x] Refuse-to-start guard: non-loopback bind without token → ap.error exit 2 (both servers)
- [x] plugin/.mcp.json updated to set AGORA_WORKSPACE via env block (no unsupported bash syntax)
- [x] setup.sh — generates token, creates workspace dir, starts bridge (python3 -m pip)
- [x] start-web-connector.sh — starts MCP HTTP server for HTTPS/claude.ai path (portable cd&&pwd)
- [x] desktop-mcp-config.json — Claude Desktop wiring snippet (Windows python note)
- [x] PR #1 reviews addressed (Kilo: merge; Augment: 5 findings fixed)
- [ ] HTTPS run + tunnel/host (user action: expose with cloudflare tunnel or ngrok)
- [ ] claude.ai custom connector registration (user action: paste HTTPS URL into claude.ai settings)

## Phase 7 — Live cross-surface test
- [x] Acceptance test script passes locally (store-level): join/claim/refuse/handoff/ack/done + all events
- [x] wire-local.sh — one command wires Claude Code + Desktop to ONE literal path, verified equal
- [ ] User runs wire-local.sh on real machine, restarts Desktop, /agora-board in Code
- [ ] Live two-surface test: claim in one → refused in other → handoff → done (paste result)
- [ ] Then add claude.ai web (start-web-connector.sh + HTTPS + Custom Connector) for full 5-surface run
