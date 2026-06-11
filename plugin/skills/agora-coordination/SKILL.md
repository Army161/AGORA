---
name: agora-coordination
description: Use when working in a shared Agora workspace alongside other Claude agents (Claude Code, Cowork, Desktop, Chrome, Design). Triggers when the user mentions Agora, a shared workspace, handoffs between agents, claiming tasks, locking files, coordinating multiple Claude sessions, or the .agora folder. Explains the protocol for joining, taking leased work, locking files, posting updates, and exchanging handoffs without colliding with other agents.
version: 0.1.0
---

# Agora coordination protocol

You share a workspace with other Claude agents through the Agora MCP server. Follow this
protocol so multiple agents never clobber each other.

## Start of session
1. `agora_join` (surface "claude_code", a stable agent_id, your role). Read the returned
   summary: active agents, open tasks, handoffs for you, recent events.
2. `agora_get_messages` for your id.

## Before doing any work
- `agora_claim_task` the task first. If it is owned with a live lease, do NOT work it —
  pick another or ask. Leases auto-expire, so a crashed agent never blocks forever.
- `agora_lock_resource` any file you are about to edit; `agora_unlock_resource` when done.
  Never edit a resource locked by someone else.

## While working
- `agora_post_update` short progress notes. They land in updates/UPDATES.md.
- `agora_update_task` to move status (in_progress / blocked / review / done).
- Poll `agora_events(since_seq)` to see what others did since you last looked — cheaper
  than re-reading the whole board.

## Handing off
- `agora_create_handoff` with a real summary, context, artifacts, and next_steps. The
  receiver runs `agora_ack_handoff` then `agora_complete_handoff`.

## Etiquette
- One task, one owner. Release (`agora_release_task`) if you stop.
- Keep updates factual and short to save everyone's context.
- The append-only event log is the source of truth; board.md is the human view.
