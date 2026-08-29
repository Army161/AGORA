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
- [x] HTTPS run + tunnel/host (cloudflared quick tunnel, verified live end-to-end)
- [x] claude.ai custom connector registration — superseded by real OAuth 2.1 (DCR + PKCE), not
      a pasted bearer token; a Custom Connector self-registers and never accepted the token path.
      Verified: connector reports connected; a cloud Claude Code session joined the room live
      through the full OAuth chain as agent `code-cloud-1`.

## Phase 7 — Live cross-surface test
- [x] Acceptance test script passes locally (store-level): join/claim/refuse/handoff/ack/done + all events
- [x] wire-local.sh — one command wires Claude Code + Desktop to ONE literal path, verified equal
- [x] User ran wire-local.ps1 on the real machine, restarted Desktop, confirmed via agora_board
- [x] The claim/refuse mutex itself is proven — 8 threads race one task in tests/test_store.py,
      exactly 1 wins — and a real cross-surface handoff (Code -> Desktop, H-0001, T-0001) shows
      in the room's actual event log. Not separately re-demoed as a live paste-the-refusal step.
- [x] claude.ai web joined live via the OAuth connector (code-cloud-1, agora_join verified,
      persisted to board.md/events.jsonl). Design/Chrome use the identical connector path but
      weren't separately confirmed joined under those surface names — same mechanism, untested
      by name.

## Phase 8 — Packaging pass (concurrent, two sessions)
- [x] Real test suite: tests/test_store.py + tests/test_billing.py, 52 tests (51 pass + 1
      intentionally-skipped live-key guard), 3 OSes x 2 Python versions in CI
- [x] CI: asserts exactly 19 agora_* tools registered; diffs plugin/server/ against server/
- [x] Two documentation sites: docs/ (GitHub Pages) and mintlify/
- [x] LICENSE (MIT), .gitignore hardening (.remember/, .env*)
- [x] Fixed a real UTF-8 encoding bug (Windows cp1252 crashed on non-Latin text in updates)
- [x] Fixed 421 Misdirected Request blocking claude.ai's connection to the tunnel
- [x] Stripe billing/entitlements scaffold (billing/) — built and tested, deliberately NOT wired
      into agora_join yet; the OSS path stays unmetered until that's switched on
- [x] verify-connector.ps1 — health-checks the full OAuth chain before a demo
- [x] PR #3 merged to main (test suite/CI/docs/OAuth/dashboard redesign, no conflicts)
- [ ] GitHub Actions CI unblocked — account is "locked due to a billing issue"; raising the
      spending limit to $5 did not fix it. Needs the account owner to resolve the actual lock
      (likely a payment-method problem), not just the spend cap.
- [ ] GitHub Pages enabled (Settings → Pages → Source = GitHub Actions) so docs/ actually deploys
