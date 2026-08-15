---
description: Claim a task safely (leased) before working it, then start.
argument-hint: [task-id] [your-agent-id]
allowed-tools: mcp__agora__agora_claim_task, mcp__agora__agora_board, mcp__agora__agora_post_update
---
Claim task "$1" for agent "$2" using `agora_claim_task` (default lease is fine).
- If it is already owned by someone else with a live lease, STOP and tell me who holds it and until when. Do not force unless I say so.
- If the claim succeeds, post a one-line `agora_post_update` saying you started it, then proceed with the task.
