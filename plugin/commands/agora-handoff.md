---
description: Hand the current work to another agent with a full handoff doc.
argument-hint: [from-agent] [to-agent-or-any] [title...]
allowed-tools: mcp__agora__agora_create_handoff, mcp__agora__agora_board
---
Create a handoff with `agora_create_handoff`.
- from_agent="$1", to_agent="$2" (use "any" if I gave "any"), title is the rest.
- Write a genuinely useful summary, the context the receiver needs, the artifacts (files/paths you produced), and concrete next_steps. Pull these from what we just did in this session — do not leave them blank.
Then confirm the handoff id and where the doc was written.
