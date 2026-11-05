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

## Turn 8 (Claude Code — security hardening + wiring helpers, PR #1)
- Replaced plain `==` token compare with `hmac.compare_digest` in bridge.py + agora_mcp.py
  (timing-side-channel fix). Vendored plugin/server synced.
- Added refuse-to-start guard: both servers `ap.error()` (exit 2) if bound to a non-loopback
  host without a token. `_is_loopback()` helper treats 127.0.0.1/localhost/::1/"" as safe.
  Verified: 0.0.0.0 no-token → refused; 127.0.0.1 no-token → starts; 0.0.0.0 +token → starts.
- plugin/.mcp.json: dropped unsupported bash `:-` default; workspace via AGORA_WORKSPACE env block.
- Added setup.sh (token gen + workspace + bridge), start-web-connector.sh (HTTP/HTTPS path,
  portable `cd && pwd` instead of realpath), desktop-mcp-config.json (Desktop snippet).
- setup.sh uses `python3 -m pip` (correct interpreter).
- Reviews: Kilo = No Issues/Merge; Augment = 5 findings, all fixed.
- Phase 7 acceptance test re-run: PASSED. py_compile clean on all 4 server files.
- Remaining (user machine): merge PR #1, then live cross-surface test + HTTPS connector.

## Turn 9 (Claude Code — wire-local.sh: one-command local wiring)
- Built wire-local.sh: resolves ONE literal absolute workspace path (pwd -P, no ~/$VAR),
  writes identical --workspace string into BOTH Claude Desktop (JSON merge, backup first,
  preserves existing servers) and Claude Code (claude mcp add -s user), then verifies both
  resolve to the same room. Modes: default write, --print, --dry-run; OS-detects Desktop
  config path (macOS/Linux/Windows); picks python3 or python.
- Kills the path-drift footgun (plugin env block vs desktop --workspace arg were two
  different mechanisms). Now one source string, verified equal.
- Tested in sandboxed HOME: merge preserved globalShortcut + existing filesystem server;
  claude mcp add ran + verified; backup written. All green.
- CONNECT.md: added "Fastest path: one command" section + literal-path warning.
- Generated a live preview of the cross-surface claim→refuse→handoff (verbatim refusal:
  "task T-0001 is owned by claude-code until ... Use force=true to override.").
- Branch note: no origin/main; claude/lucid-gauss-xrb545 is source of truth (PR #1 merged).

## Turn 10 (Claude Code — PR #2 review fixes)
- HIGH (Augment): _is_loopback("") returned True but "" binds to ALL interfaces →
  bypassed the no-token guard. Removed "" from the safe set in all 4 server files.
  This bug shipped in PR #1; PR #2's net diff now carries the fix into lucid-gauss.
- MED: wire-local.sh converts pwd -P POSIX paths to Windows-native via cygpath on
  MINGW/MSYS/CYGWIN (warns if cygpath absent).
- MED: both servers refuse to start if workspace contains the "/ABSOLUTE/PATH/TO"
  placeholder (catches unedited plugin/.mcp.json).
- Verified: ""/0.0.0.0 refused, 127.0.0.1 starts, placeholder refused, wire-local
  sandbox write preserves existing servers + verifies equal paths, Phase 7 PASSED.
- Branch note: merged origin/lucid-gauss into youthful-cori (clean) to keep PR #2
  conflict-free; force-push not used (denied + unnecessary).

## Turn 11 (Claude Code — Windows-native wiring)
- User is on Windows 11 Home (no Mac). wire-local.sh needs Git Bash/WSL; added
  wire-local.ps1 (PowerShell, guaranteed present on Win11) as the native path.
- ps1 mirrors the .sh: resolves one literal absolute Windows path, merges into
  %APPDATA%\Claude\claude_desktop_config.json (backup + preserves existing servers),
  registers Claude Code via `claude mcp add` (or prints it), verifies both equal.
  Detects Python via py/python/python3; uses absolute interpreter path for the
  Desktop command; -Print/-DryRun modes.
- CONNECT.md: "Fastest path" now shows Windows PowerShell first, then bash; prereqs noted.

## Turn 12 (Claude Code, cloud) — real OAuth web connector + dashboard redesign
- Built `AgoraOAuthProvider(OAuthAuthorizationServerProvider)` in agora_mcp.py using the mcp
  SDK's own auth module (mcp.server.auth) rather than hand-rolling: DCR (RFC 7591), PKCE
  authorize/token/refresh, and a custom /agora/consent route gating issuance behind a
  passphrase. --oauth + --public-url flags added; start-web-connector.sh/.ps1 rewritten for the
  tunnel-first ordering OAuth metadata requires. Verified against the live running server: full
  DCR->authorize->consent->token->authenticated-MCP-call chain, wrong-passphrase rejection,
  refresh rotation, real agora_join from a "design" surface persisting to board.md/events.jsonl.
- dashboard/index.html: Overview rebuilt around an "Agents in this room" hero grid
  (CSS auto-fill(minmax(240px,1fr)), no fixed slot count). bridge.py now surfaces joined_at
  (store already tracked it, was never exposed). Categorical palette ("--a-coral/-teal/-violet/
  -amber/-blue/-sage") failed the dataviz skill's validator (chroma floor + CVD separation) —
  replaced with the validated reference order, re-validated against this app's real panel
  colors. Fixed avatar-initials contrast (was white text, as low as 2.17:1 on light swatches;
  now a fixed dark ink, >=3:1 on every swatch). Verified with real Playwright screenshots
  against a live-seeded 5-agent room, not just code review.
- Merged with a concurrent session's work (test suite, CI, docs sites, LICENSE, UTF-8 fix,
  Stripe billing scaffold) via git merge — one conflict (plugin/server/bridge.py drift on the
  CI-enforced sync check), fixed by copying server/bridge.py forward. PR #3 -> main, merged.
- Doc pass: fixed docs/pitch.html self-contradicting itself (52 tests in one place, still 25 in
  another, left over from before the billing test suite landed). Added billing/ and mintlify/
  to README's repository layout — both existed with zero mention in any top-level doc.
- Unresolved: GitHub Actions "account is locked due to a billing issue" — every CI job gets
  runner_id=0, 0 billed ms. Raising the spending limit to $5 did not fix it; a lock appears to
  be a separate, more severe state (likely a payment-method problem, not a spend cap).
