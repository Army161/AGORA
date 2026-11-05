# Memory — Agora (update every turn)

## Status: All 7 phases complete and merged to main (PR #3). Web connector ships real OAuth 2.1
(DCR + PKCE), not the bearer-token stub Turn 6 left off on. Dashboard redesigned around a
scalable agent roster. Docs now ship in three places (docs/ GitHub Pages, mintlify/, this repo's
top-level .md files) plus a not-yet-wired billing/entitlements layer. Current blocker: GitHub
Actions is locked on a billing issue unrelated to the code — CI can't get a runner (see Turn 12).

## Decisions locked
- Name: **Agora** (renameable). Workspace env: `AGORA_WORKSPACE`.
- MCP is the spine; product = server + workspace + conventions, shipped as plugin + skill.
- Coordination = leased tasks + resource locks + handoffs + append-only event log.
- Engine is stdlib-only and MCP-free for testability.

## Built and verified (Turn 1)
- `server/store.py`, `server/agora_mcp.py` (16 tools), `server/requirements.txt`.
- Smoke test passed end-to-end.

## Key facts to remember
- claude.ai **web** needs HTTPS (can't reach localhost) → web hub is a hosting step,
  handed to Claude Code/user.
- All surfaces must point at the **same** workspace path to share a room.
- Tool list (16): join, board, events, post_update, create_handoff, list_handoffs,
  ack_handoff, complete_handoff, add_task, claim_task, update_task, release_task,
  lock_resource, unlock_resource, send_message, get_messages.

## Open questions for user
- HTTPS tunnel/host for claude.ai web connector: which provider? (options: cloudflare tunnel, ngrok, fly.io, render, etc.)
- Confirm absolute workspace path before wiring real app configs.

## Turn 7 — auth hardening + Phase 7 acceptance test (Claude Code, this turn)
- Added bearer-token auth to bridge.py (--token / AGORA_TOKEN env var; /state + /act gated,
  /health + dashboard serve unauthenticated; Authorization header added to CORS allow-list).
- Added bearer-token auth to agora_mcp.py HTTP mode (--token; wraps streamable_http_app()
  with Starlette BaseHTTPMiddleware; localhost-only stdio unchanged).
- Synced auth changes into plugin/server/ (vendored copy).
- Phase 7 acceptance test: PASSED. Verified: A joins + adds + claims task; B join + sees
  board; B's claim refused with error; B creates handoff; A lists/acks/completes; board.md +
  UPDATES.md + H-0001.md all written; all 6 event kinds present in log.
- Pushed to GitHub: army161/superpowers branch claude/lucid-gauss-xrb545 (waiting for repo).

## Turn 8 — security hardening + wiring helpers (PR #1, claude/youthful-cori-lzynnd)
- Patched token comparison: `hmac.compare_digest` in bridge.py + agora_mcp.py (was plain
  string ==, which is timing-side-channel vulnerable). Vendored plugin/server synced.
- AUTH GATE: both servers now REFUSE TO START (ap.error, exit 2) if bound to a non-loopback
  host without a token. `_is_loopback()` = 127.0.0.1/localhost/::1/"". So no silent open
  exposure: 0.0.0.0 + no token → refused; localhost + no token → ok; 0.0.0.0 + token → ok.
- plugin/.mcp.json: dropped unsupported bash `:-` default; workspace via AGORA_WORKSPACE env block.
- Added setup.sh (generates token via secrets.token_urlsafe(32), creates workspace, runs bridge),
  start-web-connector.sh (HTTP/HTTPS path, portable cd&&pwd not realpath, requires token),
  desktop-mcp-config.json (Claude Desktop wiring snippet).
- Reviews on PR #1: Kilo Code = No Issues/Merge; Augment = 5 findings, all fixed (mcp.json
  bash syntax, realpath, desktop env mismatch, Windows python3, bare pip).
- Phase 7 acceptance test re-verified after each change: PASSED (all 6 event kinds present).
- PR #1 open: https://github.com/Army161/AGORA/pull/1 — ready to squash-merge.

## Remaining (needs user action on real machine)
- Set `export AGORA_WORKSPACE="$HOME/.agora/<your-project>"` and
  `export AGORA_TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"`.
- Run `bash setup.sh` to smoke-test the bridge (opens localhost:8849).
- Wire Claude Code: install the plugin (see plugin/README.md).
- Wire Claude Desktop/Cowork: fill in absolute paths in desktop-mcp-config.json and
  merge the `agora` block into the desktop MCP config file, then restart the app.
- Wire claude.ai web: run `bash start-web-connector.sh`, expose port 8848 over HTTPS
  (cloudflared/ngrok), register as Custom Connector in claude.ai Settings → Connectors.
- Install skill/agora/SKILL.md as a custom skill on claude.ai / Cowork.
- Run the Phase 7 live acceptance test (two real surfaces, same workspace).

## Turn 2 — built Claude Code plugin (local hub + ./.agora chosen by user)
- plugin/: plugin.json, .mcp.json (server via ${CLAUDE_PLUGIN_ROOT}, workspace ./.agora),
  5 commands, agora-coordination skill, agora-coordinator agent, vendored server, README.
- JSON validated. Decision: v1 = local hub, project-local ./.agora workspace.
- Next: Phase 3 standalone skill for chat surfaces (claude.ai/Cowork) hitting same server.

## Turn 3 — built standalone skill (chat surfaces)
- skill/agora/SKILL.md mirrors the plugin protocol for claude.ai / Cowork / Design.
- Assumes Agora MCP connected (web=HTTPS custom connector, Cowork=desktop MCP), same workspace.
- Confirmed goal alignment with user (human-in-loop coordination room across 5 surfaces).
- Next: Phase 4 per-surface connect guides (concrete config for all 5).

## Turn 4 — connect guide
- Wrote CONNECT.md: all 5 surfaces -> one room. Golden rule = same ABSOLUTE workspace path;
  engine is cross-process safe (multiple stdio servers on one folder OK).
- Local hub (stdio) for Code/Desktop/Cowork/Design/Chrome; web = Phase 6 HTTPS connector.
- Honest notes: Chrome/Design are thinnest participants (verify tool exposure per build).
- Next: Phase 5 optional human web dashboard (reads board.md + events.jsonl).

## Turn 5 — flagship dashboard (Phase 5, expanded by user request)
- Built dashboard/index.html: single-file, vanilla JS, no deps; warm editorial+terminal
  aesthetic (Fraunces + IBM Plex), dark/light, responsive, Cmd-K palette, keyboard nav,
  skeleton load, empty states, toasts, live-tweening KPIs, lease countdowns, self-animating demo.
- Views: Overview, Workspace (multi-pane parallel), Task Queue (+auto-route orchestration),
  Threads, Shared Memory + house-style output controls, Execution Log, Settings (rules editor).
- Data layer mirrors Agora schema exactly; `Adapter` is the single seam to go live (Phase 6).
- JS node --check clean. Honest: routes/assigns; agents execute in their own surfaces.
- Next: Phase 6 live bridge + claude.ai web connector + Phase 7 cross-surface test (Claude Code).

## Turn 6 — live bridge + shared memory + handoff
- Engine: added shared memory (pinned facts + house style) + get_memory/add_pin/set_style;
  fixed cold-start (root dir now created in __init__).
- MCP: +3 tools (agora_pin_fact, agora_set_house_style, agora_get_memory) → 19 total.
- bridge.py: GET /state (dashboard-shaped, ms times, presence/load), POST /act (add_task,
  route_task/route_all by rules, task_done, assign, message, handoff, pin, set_style,
  set_settings), serves dashboard, CORS, --seed. Tested end-to-end via curl: all green.
- dashboard: auto-connects to bridge (live) else demo seed; writes route through /act; polls.
- plugin/server re-vendored. HANDOFF.md created for Claude Code (Phase 6 tail + Phase 7).
- LEFT FOR CLAUDE CODE: wire real apps, claude.ai web HTTPS connector, auth token, live test.

## Turn 12 — real OAuth, dashboard redesign, packaging pass (Claude Code, cross-surface)
- The bearer-token web connector from Turn 6 could not satisfy claude.ai's Custom Connector
  flow (it self-registers via RFC 7591 DCR, then does authorization-code + PKCE). Replaced with
  a real OAuth 2.1 authorization server using the mcp SDK's own provider protocol: any client
  self-registers, but nobody gets a token without the room passphrase at /agora/consent.
  Verified end-to-end live: DCR, PKCE authorize, wrong-passphrase rejection, token exchange,
  refresh rotation, an authenticated MCP session, a real agora_join persisting to disk.
- Dashboard redesigned: Overview now leads with a full "Agents in this room" grid (CSS
  auto-fill, no cap — the "only shows 2 agents" complaint was a layout problem, not a code cap).
  Categorical agent-surface palette re-picked and run through the dataviz skill's validator
  after the original hand-picked colors failed contrast/CVD checks.
- A concurrent session (Claude Opus 5, via the user's Desktop) independently added: a 52-test
  suite (tests/test_store.py + tests/test_billing.py), 3-OS CI, a GitHub Pages docs site, a
  mintlify/ docs site, LICENSE, a UTF-8 encoding fix (Windows cp1252 crashed on non-Latin text),
  a Stripe billing/entitlements layer (built but NOT wired into agora_join — free tier caps at
  2 agents on paper only), and a fix for 421 Misdirected Request blocking claude.ai's connection.
  Both lines of work merged cleanly via git merge (no force-push, no discarded work) — PR #3
  merged to main. All three agents (Code, Desktop, and this cloud session as code-cloud-1)
  coordinated live in the actual Agora room while doing this, proof the product works on itself.
- Current blocker: GitHub Actions returns "account is locked due to a billing issue" — every
  job gets runner_id=0 and 0 billed ms (never allocated a runner), not a test/code failure.
  Raising the account's Actions spending limit to $5 did NOT clear it — a lock is a different,
  more severe state than a $0 spending limit (usually a payment-method problem). Unresolved.
- Workaround already available if CI stays blocked: Settings > Pages > Deploy from a branch
  publishes docs/ without touching Actions minutes at all.
