# Handoff → Claude Code

Agora is a shared room where the Claude surfaces (claude.ai, Cowork, Claude Code, Chrome,
Design) coordinate: leased tasks, file locks, handoffs, updates, shared memory, an
append-only event log, a human dashboard. Built and tested in a sandbox through Phase 6
(local live path). What remains needs a real machine, the real apps, and accounts — your job.

## State of the build
Done + verified here: workspace engine, 19-tool MCP server, Claude Code plugin, standalone
skill, 5-surface connect guide, flagship dashboard, and the live bridge (dashboard ⇄ real
`.agora`). Remaining: claude.ai **web** over HTTPS + auth hardening (Phase 6 tail) and the
live cross-surface acceptance test (Phase 7).

## Repo map
```
server/store.py        engine (stdlib): presence, tasks+leases, handoffs, updates, locks,
                       messages, events, shared memory, board render. Cross-process safe.
server/agora_mcp.py    MCP server, 19 tools, stdio + --http
server/bridge.py       HTTP bridge: GET /state, POST /act, serves dashboard; --seed
dashboard/index.html   single-file cockpit; auto-connects to the bridge (else demo)
plugin/                Claude Code plugin (.mcp.json auto-wires the server) + vendored server
skill/agora/SKILL.md   standalone skill for chat surfaces
CONNECT.md             per-surface wiring   plan.md/architecture.md/build.md/memory.md/todolist.md  the brain
```

## Run it locally (fastest path to "alive")
```bash
pip install -r server/requirements.txt
python3 server/bridge.py --workspace ~/projects/app/.agora --seed --port 8849
# open http://localhost:8849  → dashboard live on the real workspace
```
The MCP server (for the agent surfaces) runs separately against the SAME folder:
```bash
python3 server/agora_mcp.py --workspace ~/projects/app/.agora            # stdio
python3 server/agora_mcp.py --http --port 8848 --workspace ~/projects/app/.agora   # for web
```
Cross-process safe: bridge + several stdio servers can share one folder at once.

## Your tasks
1. **Wire the 5 surfaces** to the SAME absolute workspace (see CONNECT.md). Confirm each
   app's current MCP config location at https://docs.claude.com / https://support.claude.com.
   - Claude Code: install `plugin/` (or add the `.mcp.json` server) with an absolute `--workspace`.
   - Desktop/Cowork: add the server to the desktop MCP config. Design/Chrome inherit it.
2. **claude.ai web (Phase 6 tail).** Run `agora_mcp.py --http`, expose over HTTPS (tunnel or
   host), register it as a Custom Connector, install `skill/agora/SKILL.md`.
3. **Add auth before exposing anything publicly** (needed for #2):
   - Bridge: require a header (e.g. `Authorization: Bearer <token>`) in `H.do_*`; reject otherwise.
   - MCP http mode: put it behind the same token / a reverse proxy. Localhost-only stays open.
4. **Live acceptance test (Phase 7).** With ≥2 surfaces on one workspace:
   a. A: `agora_join` → `agora_add_task` → `agora_claim_task`.
   b. B: `agora_join` → `agora_board` (sees A + task) → claim same task → must be refused
      → `agora_create_handoff` to A.
   c. A: `agora_list_handoffs` → `agora_ack_handoff` → `agora_complete_handoff`.
   d. Watch it all land live in the dashboard and in `$WS/board.md`, `updates/UPDATES.md`,
      `handoffs/*.md`.
5. **Review.** Skim store.py concurrency (mkdir-mutex + atomic writes + leases) and the
   bridge action map. Add tests if you want regression cover.

## Known limits to verify on real apps
- Exact MCP config path/format per app (moves over time — check live docs).
- Whether Chrome/Design expose third-party MCP tools in the user's build; if not, they ride
  via Cowork or read `board.md` (documented in CONNECT.md).
- The dashboard's settings inputs (theme/density/workspace) are local-only except rules,
  which persist via `/act set_settings`. Wire the rest if desired.

## Definition of done
All five surfaces join one room; a task claimed in one is refused in another; a handoff
flows A→B→done; the dashboard reflects every change live; nothing requires a surface to
re-explain the project. Then it's shipping.
