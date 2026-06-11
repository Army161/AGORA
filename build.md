# Build log — Agora

## Turn 1
- Read skills: mcp-builder (+python guide), plugin-structure, command-development.
- Verified FastMCP API: `run(transport=stdio|sse|streamable-http)`, `settings.host/port`.
- Built `server/store.py` (stdlib engine): presence, tasks+leases, handoffs, updates,
  locks, messages, event log, board renderer, atomic writes, mkdir-mutex.
- Built `server/agora_mcp.py`: 16 tools, Pydantic-validated, stdio + `--http`.
- Tests: `py_compile` OK; `--help` OK; full end-to-end smoke test OK (join, task claim +
  collision, handoff ack/complete, update feed, lock collision, messages, events, board,
  on-disk artifacts all verified).
- Wrote brain docs (this set) + packaged v0.1.

## How to build/run
- `pip install -r server/requirements.txt`
- stdio: `python server/agora_mcp.py --workspace ~/.agora/PROJECT`
- http:  `python server/agora_mcp.py --http --host 0.0.0.0 --port 8848 --workspace ~/.agora/PROJECT`
- test:  `python -m py_compile server/*.py` then the smoke test in this repo's history.

## Next turn
- Phase 2: Claude Code plugin (`plugin/.claude-plugin/plugin.json`, `.mcp.json` wiring the
  server via `${CLAUDE_PLUGIN_ROOT}`, commands: /agora-join /agora-board /agora-handoff,
  bundled skill, optional coordinator agent).
- Phase 3: standalone skill mirroring the plugin for chat surfaces.

## Turn 2
- User chose local hub + project-local ./.agora.
- Built Claude Code plugin: manifest, .mcp.json (${CLAUDE_PLUGIN_ROOT} + workspace ./.agora),
  commands (join/board/take/update/handoff), bundled agora-coordination skill,
  agora-coordinator subagent, vendored server, plugin README. JSON validated.
- Next: Phase 3 standalone skill mirroring the plugin for chat surfaces.

## Turn 3
- Built standalone skill skill/agora/SKILL.md for chat surfaces; mirrors plugin protocol,
  includes connect-check + identity + full protocol + tool reference.
- Next: Phase 4 per-surface connection guides.

## Turn 4
- Built CONNECT.md (per-surface wiring for all 5, local hub). Absolute-path golden rule;
  noted cross-process safety; web deferred to Phase 6. Updated trackers.
- Next: Phase 5 dashboard.

## Turn 5
- Built flagship dashboard (single-file HTML, 57KB). All requested components present:
  persistent sidebar, shared memory panel (dock + view), orchestration/auto-route, multi-pane
  parallel workspace, task queue + exec log, inter-agent threads, output-consistency house style,
  global settings. Dark/light, responsive, keyboard, animations, skeletons, empty/error, live KPIs.
  Data layer mirrors Agora schema; Adapter seam documented for Phase 6. JS syntax verified.

## Turn 6
- Shared memory added to engine + 3 MCP tools (19 total). Cold-start root bug fixed.
- Built server/bridge.py (live dashboard<->.agora) — tested with curl (state/act/seed/serve).
- Dashboard rewired: Adapter auto-detects bridge; commit()/refreshLive(); demo fallback. JS checked.
- Re-vendored plugin/server. Wrote HANDOFF.md. Remaining work = Claude Code (web + auth + live test).

## Turn 7 (Claude Code)
- Installed deps (mcp 1.27.2, pydantic 2.x, uvicorn, starlette, etc.). Verified py_compile clean.
- Ran bridge --seed + curl smoke test: /health OK, /state 6 agents 5 tasks 19 events.
- Added bearer-token auth to bridge.py: TOKEN global, _auth_ok() helper, /state + /act gated
  (401 without/wrong token), /health + dashboard unguarded. CORS allow-list extended.
  --token flag + AGORA_TOKEN env var; prints token at startup.
- Added bearer-token auth to agora_mcp.py HTTP mode: --token / AGORA_TOKEN; BearerAuthMiddleware
  (Starlette BaseHTTPMiddleware) wraps streamable_http_app(); no-token falls through to
  mcp.run() as before. Prints auth mode at startup.
- Synced both changes into plugin/server/ (vendored copy).
- Phase 7 acceptance test PASSED: A join+add+claim; B join+board+refuse-claim+create-handoff;
  A list+ack+complete; board.md + UPDATES.md + H-0001.md verified; all 6 event kinds present.
- Updated memory.md / todolist.md / build.md. Next: HTTPS tunnel + real surface wiring (user).
