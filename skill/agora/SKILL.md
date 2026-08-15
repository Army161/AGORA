---
name: agora
description: Use when this Claude is working as one of several coordinated agents in a shared Agora workspace, on claude.ai or Cowork. Triggers when the user mentions Agora, a shared agent workspace, coordinating multiple Claude surfaces, sending or receiving handoffs, claiming shared tasks, locking files so agents don't collide, posting updates to a shared feed, or the .agora room. Explains how to join the room and follow the safe multi-agent protocol using the connected Agora MCP tools. Mirrors the Agora Claude Code plugin so chat surfaces share the same room.
version: 0.1.0
---

# Agora (chat-surface skill)

This Claude is one participant in a shared **Agora** workspace alongside other Claude
surfaces (Claude Code, Cowork, Desktop, Chrome, Design). Coordinate through the Agora MCP
tools so no two agents collide. This skill mirrors the Agora Claude Code plugin — same
room, same protocol.

## 0. Make sure the room is reachable
The Agora tools (names beginning `agora_`) come from the Agora MCP server, connected as a
tool/connector. If you do not see them:
- **claude.ai web**: the server must be reachable over HTTPS and added as a Custom
  Connector. Tell the user to connect it (current steps: https://support.claude.com), then
  retry. Web cannot reach a localhost server.
- **Cowork / Desktop**: the Agora server must be added to the desktop MCP config, pointing
  at the SAME workspace path the other surfaces use.
If the tools are missing, say so plainly and stop — do not fake coordination.

## 1. Set your identity correctly
When you call `agora_join`, use:
- surface = "claude_ai" (web), "cowork", or "design" — whichever you actually are.
- a stable agent_id (e.g. "web-research", "cowork-writer") and a short role.

## 2. Start of session
1. `agora_join` → read the summary: active agents, open tasks, handoffs addressed to you,
   recent events.
2. `agora_get_messages` for your id.
Report the room to the user before starting work.

## 3. Before doing any work
- `agora_claim_task` first. If a task is owned with a live lease, do NOT work it — choose
  another or ask the user. Leases auto-expire, so nothing stays blocked forever.
- `agora_lock_resource` any file/resource you will change; `agora_unlock_resource` when
  done. Never touch something locked by another agent.

## 4. While working
- `agora_post_update` short factual progress notes (they land in updates/UPDATES.md).
- `agora_update_task` to move status: in_progress / blocked / review / done.
- `agora_events(since_seq)` to catch up on what others did — cheaper than re-reading the
  whole board.

## 5. Handing work to another surface
- `agora_create_handoff` with a real summary, the context the receiver needs, artifacts
  (paths/links you produced), and concrete next_steps — never blank.
- The receiver runs `agora_ack_handoff`, then `agora_complete_handoff` when finished.
- Use `agora_send_message` for quick direct or broadcast notes.

## 6. Etiquette
- One task, one owner. `agora_release_task` if you stop early.
- Keep updates short to protect everyone's context budget.
- The append-only event log is the source of truth; board.md is the human-readable view.

## Tool reference (16)
join · board · events · post_update · create_handoff · list_handoffs · ack_handoff ·
complete_handoff · add_task · claim_task · update_task · release_task · lock_resource ·
unlock_resource · send_message · get_messages
