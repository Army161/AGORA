"""agora_mcp — MCP server exposing the Agora shared workspace to any Claude surface.

Run local (stdio, for Claude Code / Desktop / Cowork):
    python agora_mcp.py --workspace ~/.agora/myproject
Run remote (HTTP, required for claude.ai web connectors):
    python agora_mcp.py --http --host 0.0.0.0 --port 8848 --workspace ~/.agora/myproject
    python agora_mcp.py --http --token mysecret ...   # add auth before exposing publicly

Every connected surface that points at the SAME workspace shares one room.
"""
from __future__ import annotations
import argparse, json, os
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP
from store import AgoraStore, DEFAULT_LEASE_MINUTES

mcp = FastMCP("agora_mcp")
STORE: Optional[AgoraStore] = None

def _store() -> AgoraStore:
    global STORE
    if STORE is None:
        STORE = AgoraStore(os.environ.get("AGORA_WORKSPACE", "~/.agora/default"),
                           os.environ.get("AGORA_NAME", "Agora Workspace"))
    return STORE

def _j(obj) -> str: return json.dumps(obj, indent=2, default=str)

class Surface(str, Enum):
    claude_ai = "claude_ai"; cowork = "cowork"; claude_code = "claude_code"
    chrome = "chrome"; design = "design"; other = "other"

class _M(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

# ---- presence ----
class JoinIn(_M):
    agent_id: str = Field(..., description="Unique id for this agent, e.g. 'code-1' or 'web-frontend'", min_length=1, max_length=60)
    surface: Surface = Field(..., description="Which Claude surface you are")
    role: str = Field("", description="Optional role, e.g. 'frontend', 'researcher'", max_length=80)
    display_name: str = Field("", description="Optional friendly name", max_length=80)

@mcp.tool(name="agora_join", annotations={"title": "Join the workspace", "readOnlyHint": False, "idempotentHint": True})
async def agora_join(params: JoinIn) -> str:
    """Announce presence and get caught up. Call this first every session.
    Returns the current board: active agents, open tasks, handoffs addressed to you, recent events."""
    return _j(_store().join(params.agent_id, params.surface.value, params.role, params.display_name))

@mcp.tool(name="agora_board", annotations={"title": "Read the board", "readOnlyHint": True})
async def agora_board() -> str:
    """Read the current shared board (agents, tasks, locks, open handoffs, recent activity)."""
    return _j(_store().summary())

class EventsIn(_M):
    since_seq: int = Field(0, description="Return events with seq greater than this", ge=0)
    limit: int = Field(50, description="Max events", ge=1, le=200)

@mcp.tool(name="agora_events", annotations={"title": "Event log tail", "readOnlyHint": True})
async def agora_events(params: EventsIn) -> str:
    """What changed since you last looked. Poll with the last seq you saw to catch up incrementally."""
    return _j(_store().events(params.since_seq, params.limit))

# ---- updates ----
class UpdateIn(_M):
    agent_id: str = Field(..., min_length=1, max_length=60)
    message: str = Field(..., description="Short progress note", min_length=1, max_length=2000)
    task_id: Optional[str] = Field(None, description="Related task id, e.g. 'T-0003'")
    tags: Optional[List[str]] = Field(default_factory=list, max_items=10)

@mcp.tool(name="agora_post_update", annotations={"title": "Post a status update", "readOnlyHint": False})
async def agora_post_update(params: UpdateIn) -> str:
    """Post a progress update to the shared updates feed (updates/UPDATES.md) and event log."""
    return _j(_store().post_update(params.agent_id, params.message, params.task_id, params.tags))

# ---- handoffs ----
class HandoffIn(_M):
    from_agent: str = Field(..., min_length=1, max_length=60)
    to_agent: str = Field("any", description="Target agent_id, or 'any' for the next available", max_length=60)
    title: str = Field(..., min_length=1, max_length=160)
    summary: str = Field(..., description="What is being handed off and why", min_length=1, max_length=4000)
    context: str = Field("", description="Background the receiver needs", max_length=8000)
    artifacts: Optional[List[str]] = Field(default_factory=list, description="File paths / links produced", max_items=50)
    next_steps: Optional[List[str]] = Field(default_factory=list, max_items=50)
    task_id: Optional[str] = Field(None)

@mcp.tool(name="agora_create_handoff", annotations={"title": "Create a handoff", "readOnlyHint": False})
async def agora_create_handoff(params: HandoffIn) -> str:
    """Hand work to another agent. Writes a handoff doc (handoffs/H-XXXX.md) and notifies via the board."""
    return _j(_store().create_handoff(params.from_agent, params.to_agent, params.title, params.summary,
              params.context, params.artifacts, params.next_steps, params.task_id))

class ListHandoffsIn(_M):
    for_agent: Optional[str] = Field(None, description="Filter to handoffs to/from this agent")
    status: Optional[str] = Field(None, description="open | acked | done")
    limit: int = Field(20, ge=1, le=100)

@mcp.tool(name="agora_list_handoffs", annotations={"title": "List handoffs", "readOnlyHint": True})
async def agora_list_handoffs(params: ListHandoffsIn) -> str:
    """List handoffs, optionally filtered for you and by status."""
    return _j(_store().list_handoffs(params.for_agent, params.status, params.limit))

class HandoffActionIn(_M):
    handoff_id: str = Field(..., min_length=1, max_length=20)
    agent_id: str = Field(..., min_length=1, max_length=60)
    note: str = Field("", max_length=4000)

@mcp.tool(name="agora_ack_handoff", annotations={"title": "Accept a handoff", "readOnlyHint": False})
async def agora_ack_handoff(params: HandoffActionIn) -> str:
    """Accept a handoff (marks it 'acked' so others know you own it)."""
    return _j(_store().ack_handoff(params.handoff_id, params.agent_id, params.note))

@mcp.tool(name="agora_complete_handoff", annotations={"title": "Complete a handoff", "readOnlyHint": False})
async def agora_complete_handoff(params: HandoffActionIn) -> str:
    """Mark a handoff done, recording the result in its log."""
    return _j(_store().complete_handoff(params.handoff_id, params.agent_id, params.note))

# ---- tasks ----
class AddTaskIn(_M):
    title: str = Field(..., min_length=1, max_length=160)
    created_by: str = Field(..., min_length=1, max_length=60)
    description: str = Field("", max_length=8000)
    tags: Optional[List[str]] = Field(default_factory=list, max_items=10)
    blocked_by: Optional[List[str]] = Field(default_factory=list, max_items=20)

@mcp.tool(name="agora_add_task", annotations={"title": "Add a task", "readOnlyHint": False})
async def agora_add_task(params: AddTaskIn) -> str:
    """Add a task to the shared task list."""
    return _j(_store().add_task(params.title, params.created_by, params.description, params.tags, params.blocked_by))

class ClaimTaskIn(_M):
    task_id: str = Field(..., min_length=1, max_length=20)
    agent_id: str = Field(..., min_length=1, max_length=60)
    ttl_minutes: int = Field(DEFAULT_LEASE_MINUTES, description="Lease length; auto-expires so a crashed agent never blocks", ge=1, le=1440)
    force: bool = Field(False, description="Override a live lease held by someone else")

@mcp.tool(name="agora_claim_task", annotations={"title": "Claim a task", "readOnlyHint": False})
async def agora_claim_task(params: ClaimTaskIn) -> str:
    """Lease a task so no other agent works it simultaneously. Fails if actively owned unless force=true."""
    return _j(_store().claim_task(params.task_id, params.agent_id, params.ttl_minutes, params.force))

class UpdateTaskIn(_M):
    task_id: str = Field(..., min_length=1, max_length=20)
    agent_id: str = Field(..., min_length=1, max_length=60)
    status: Optional[str] = Field(None, description="todo | in_progress | blocked | review | done")
    note: str = Field("", max_length=2000)
    extend_minutes: Optional[int] = Field(None, description="Extend the lease by N minutes", ge=1, le=1440)

@mcp.tool(name="agora_update_task", annotations={"title": "Update a task", "readOnlyHint": False})
async def agora_update_task(params: UpdateTaskIn) -> str:
    """Change a task's status, add a note, or extend the lease. status=done frees the task."""
    return _j(_store().update_task(params.task_id, params.agent_id, params.status, params.note, params.extend_minutes))

class ReleaseTaskIn(_M):
    task_id: str = Field(..., min_length=1, max_length=20)
    agent_id: str = Field(..., min_length=1, max_length=60)

@mcp.tool(name="agora_release_task", annotations={"title": "Release a task", "readOnlyHint": False})
async def agora_release_task(params: ReleaseTaskIn) -> str:
    """Give a task back to the pool (status -> todo, lease cleared)."""
    return _j(_store().release_task(params.task_id, params.agent_id))

# ---- locks ----
class LockIn(_M):
    resource: str = Field(..., description="What you're locking, e.g. a file path 'src/app.py'", min_length=1, max_length=300)
    agent_id: str = Field(..., min_length=1, max_length=60)
    ttl_minutes: int = Field(DEFAULT_LEASE_MINUTES, ge=1, le=1440)
    note: str = Field("", max_length=500)
    force: bool = Field(False)

@mcp.tool(name="agora_lock_resource", annotations={"title": "Lock a resource", "readOnlyHint": False})
async def agora_lock_resource(params: LockIn) -> str:
    """Claim an editing lock on a file/resource so two surfaces don't clobber each other. Auto-expires."""
    return _j(_store().lock_resource(params.resource, params.agent_id, params.ttl_minutes, params.note, params.force))

class UnlockIn(_M):
    resource: str = Field(..., min_length=1, max_length=300)
    agent_id: str = Field(..., min_length=1, max_length=60)

@mcp.tool(name="agora_unlock_resource", annotations={"title": "Unlock a resource", "readOnlyHint": False})
async def agora_unlock_resource(params: UnlockIn) -> str:
    """Release a resource lock you hold."""
    return _j(_store().unlock_resource(params.resource, params.agent_id))

# ---- messages ----
class SendMsgIn(_M):
    from_agent: str = Field(..., min_length=1, max_length=60)
    to_agent: str = Field("all", description="Target agent_id or 'all' to broadcast", max_length=60)
    body: str = Field(..., min_length=1, max_length=4000)

@mcp.tool(name="agora_send_message", annotations={"title": "Send a message", "readOnlyHint": False})
async def agora_send_message(params: SendMsgIn) -> str:
    """Send a direct or broadcast message to other agents in the room."""
    return _j(_store().send_message(params.from_agent, params.to_agent, params.body))

class GetMsgIn(_M):
    agent_id: str = Field(..., min_length=1, max_length=60)
    limit: int = Field(20, ge=1, le=100)

@mcp.tool(name="agora_get_messages", annotations={"title": "Get messages", "readOnlyHint": True})
async def agora_get_messages(params: GetMsgIn) -> str:
    """Get messages addressed to you (or broadcast to all)."""
    return _j(_store().get_messages(params.agent_id, params.limit))

class PinIn(_M):
    agent_id: str = Field(..., min_length=1, max_length=60)
    text: str = Field(..., min_length=1, max_length=2000)

@mcp.tool(name="agora_pin_fact", annotations={"title": "Pin a shared fact", "readOnlyHint": False})
async def agora_pin_fact(params: PinIn) -> str:
    """Pin a fact to shared memory that every agent reads before acting."""
    return _j(_store().add_pin(params.text, params.agent_id))

class StyleIn(_M):
    voice: Optional[str] = None
    format: Optional[str] = None
    citations: Optional[str] = None
    maxlen: Optional[str] = None

@mcp.tool(name="agora_set_house_style", annotations={"title": "Set house style", "readOnlyHint": False})
async def agora_set_house_style(params: StyleIn) -> str:
    """Set the shared house style (voice, format, citations, length) all agents follow for output consistency."""
    return _j(_store().set_style(params.model_dump(exclude_none=True)))

@mcp.tool(name="agora_get_memory", annotations={"title": "Read shared memory", "readOnlyHint": True})
async def agora_get_memory() -> str:
    """Read shared memory: pinned facts + house style."""
    return _j(_store().get_memory())

def main():
    global STORE
    ap = argparse.ArgumentParser(description="Agora MCP server — shared workspace for Claude surfaces")
    ap.add_argument("--workspace", default=os.environ.get("AGORA_WORKSPACE", "~/.agora/default"),
                    help="Path to the shared workspace dir (all surfaces must use the same one)")
    ap.add_argument("--name", default=os.environ.get("AGORA_NAME", "Agora Workspace"))
    ap.add_argument("--http", action="store_true", help="Serve over streamable HTTP (needed for claude.ai web)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8848)
    ap.add_argument("--token", default=os.environ.get("AGORA_TOKEN", ""),
                    help="Bearer token for HTTP mode. Required when exposed beyond localhost. "
                         "Can also be set via AGORA_TOKEN env var.")
    args = ap.parse_args()
    STORE = AgoraStore(args.workspace, args.name)
    if args.http:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        token = args.token or None
        if token:
            # Wrap the ASGI app with a simple bearer-token middleware.
            import uvicorn
            from starlette.middleware.base import BaseHTTPMiddleware
            from starlette.responses import JSONResponse

            class BearerAuthMiddleware(BaseHTTPMiddleware):
                async def dispatch(self, request, call_next):
                    auth = request.headers.get("Authorization", "")
                    if auth != f"Bearer {token}":
                        return JSONResponse({"error": "unauthorized"}, status_code=401)
                    return await call_next(request)

            app = mcp.streamable_http_app()
            wrapped = BearerAuthMiddleware(app)
            print(f"Agora MCP HTTP on http://{args.host}:{args.port}  auth=bearer-token")
            uvicorn.run(wrapped, host=args.host, port=args.port)
        else:
            print(f"Agora MCP HTTP on http://{args.host}:{args.port}  auth=none (localhost-only)")
            mcp.run(transport="streamable-http")
    else:
        mcp.run()

if __name__ == "__main__":
    main()
