---
description: Join the Agora shared workspace and get caught up on agents, tasks, and handoffs.
argument-hint: [agent-id] [role]
allowed-tools: mcp__agora__agora_join, mcp__agora__agora_get_messages
---
You are joining the shared Agora workspace as a Claude Code agent.

Call `agora_join` with:
- agent_id: "$1" if provided, else a short id like "code-1"
- surface: "claude_code"
- role: "$2" if provided

Then summarize for me, briefly: who else is active, open tasks, and any handoffs addressed to me. Also check `agora_get_messages` for my id. Do not start work yet — just report the room.
