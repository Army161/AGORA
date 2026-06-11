# Claude Workspace dashboard

`dashboard/index.html` is the human cockpit over the Agora room. Open it in any browser —
no build, no dependencies, single file. Dark/light, responsive, keyboard-driven.

## What it shows
- **Sidebar**: switch views, switch/focus agents (presence dots, current task).
- **Overview**: live KPIs, activity table, agent roster.
- **Workspace**: multi-pane grid — every agent's current task, progress, recent updates,
  quick actions (assign / handoff / message). Focus one agent or watch all in parallel.
- **Task Queue**: sortable table, lease countdowns, **auto-route** (orchestration by tag→
  surface rules), per-task route, mark done.
- **Threads**: handoffs + messages between agents.
- **Shared Memory**: pinned facts + the **house style** (output-consistency controls)
  every agent follows. Also a slide-over dock reachable from any view (press M).
- **Execution Log**: the append-only event stream.
- **Settings**: workspace path, orchestration rules editor, theme/density, reset.
- Command palette (Cmd/Ctrl-K or /), number keys 1–7 for views, T theme, M memory, Esc.

## Honest scope
It runs on a built-in data layer that **mirrors the Agora store schema exactly**
(agents, tasks+leases, handoffs, updates, events, messages, locks, memory). It ships with
a live demo scenario and gently self-animates so you can see the behavior. The
orchestration layer **routes and assigns** tasks to agents by rule; the agents still do
the real work inside their own surfaces — by design.

## Going live (Phase 6, with Claude Code)
The only seam to change is the `Adapter` object near the top of the script:
- `Adapter.load()` currently returns seed data. Point it at a tiny read bridge that
  serves the `.agora` JSON files (agents.json, tasks.json, handoffs/index.json,
  events.jsonl, etc.) as one JSON payload.
- `Adapter.act(fn)` currently mutates local state. Point it at write endpoints that call
  the matching Agora MCP tools (add_task, claim_task, create_handoff, post_update, …).
A ~40-line local HTTP bridge that reads the workspace folder and forwards writes to the
server is enough. That bridge + auth is Phase 6 work and lives in handoff-to-claude-code.md.
