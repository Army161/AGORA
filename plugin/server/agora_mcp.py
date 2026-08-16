"""agora_mcp — MCP server exposing the Agora shared workspace to any Claude surface.

Run local (stdio, for Claude Code / Desktop / Cowork):
    python agora_mcp.py --workspace ~/.agora/myproject
Run remote (HTTP, required for claude.ai web connectors):
    # A non-loopback bind REQUIRES a token — the server refuses to start without one.
    AGORA_TOKEN=$(openssl rand -hex 32) \
      python agora_mcp.py --http --host 0.0.0.0 --port 8848 --workspace ~/.agora/myproject

    # Loopback-only needs no token, but note that putting a tunnel in front of a
    # loopback bind exposes it publicly without tripping that guard — set a token there too.
    python agora_mcp.py --http --host 127.0.0.1 --port 8848 --workspace ~/.agora/myproject

Every connected surface that points at the SAME workspace shares one room.
"""
from __future__ import annotations
import argparse, hmac, json, os, secrets, time
from enum import Enum
from typing import Dict, Optional, List
from urllib.parse import urlparse
from pydantic import AnyHttpUrl, BaseModel, Field, ConfigDict
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    ProviderTokenVerifier,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
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

def _is_loopback(host: str) -> bool:
    """True only for hosts that are unreachable from other machines.
    Note: "" / "0.0.0.0" / "::" bind to ALL interfaces — never loopback."""
    return host in ("127.0.0.1", "localhost", "::1")

# ---- OAuth 2.1 authorization server (Dynamic Client Registration + PKCE) -----
# claude.ai (and any spec-compliant MCP client) attaches to a remote connector by
# discovering OAuth metadata, self-registering a client (RFC 7591), then sending the
# owner's browser through a normal authorization-code + PKCE flow (RFC 6749 / 7636).
# A static bearer token alone can't satisfy that discovery/registration handshake —
# there's nothing to register with. This implements the real handshake: anyone can
# register a client (that's normal for public MCP connectors), but nobody gets an
# authorization code without typing the passphrase on the /agora/consent page, which
# only the room's owner has. Everything here is in-memory: it resets on restart,
# which is fine — surfaces just reauthorize once, same as any local dev OAuth server.
_OAUTH_PROVIDER: "Optional[AgoraOAuthProvider]" = None
ACCESS_TOKEN_TTL_SECONDS = 3600 * 24        # 1 day
REFRESH_TOKEN_TTL_SECONDS = 3600 * 24 * 90  # 90 days
AUTH_CODE_TTL_SECONDS = 600                 # 10 minutes to complete the redirect
CONSENT_REQUEST_TTL_SECONDS = 600

class AgoraOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    def __init__(self, passphrase: str, public_url: str, room_name: str):
        self.passphrase = passphrase
        self.public_url = public_url.rstrip("/")
        self.room_name = room_name
        self.clients: Dict[str, OAuthClientInformationFull] = {}
        self.pending: Dict[str, tuple] = {}          # request_id -> (client_id, AuthorizationParams, expires_at)
        self.auth_codes: Dict[str, AuthorizationCode] = {}
        self.access_tokens: Dict[str, AccessToken] = {}
        self.refresh_tokens: Dict[str, RefreshToken] = {}

    # -- clients (RFC 7591 Dynamic Client Registration) --
    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self.clients[client_info.client_id] = client_info

    # -- authorize: hand the browser to our own consent page instead of a 3rd party --
    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        request_id = secrets.token_urlsafe(24)
        self.pending[request_id] = (client.client_id, params, time.time() + CONSENT_REQUEST_TTL_SECONDS)
        return f"{self.public_url}/agora/consent?request_id={request_id}"

    def complete_consent(self, request_id: str) -> Optional[tuple]:
        entry = self.pending.get(request_id)
        if not entry:
            return None
        client_id, params, expires_at = entry
        if expires_at < time.time():
            del self.pending[request_id]
            return None
        return client_id, params

    def issue_code(self, request_id: str) -> Optional[str]:
        """Called only after the passphrase has been verified. Single-use request_id."""
        entry = self.pending.pop(request_id, None)
        if not entry:
            return None
        client_id, params, expires_at = entry
        if expires_at < time.time():
            return None
        code = secrets.token_urlsafe(32)
        self.auth_codes[code] = AuthorizationCode(
            code=code,
            scopes=params.scopes or [],
            expires_at=time.time() + AUTH_CODE_TTL_SECONDS,
            client_id=client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    # -- authorization code -> tokens --
    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> Optional[AuthorizationCode]:
        ac = self.auth_codes.get(authorization_code)
        return ac if ac and ac.client_id == client.client_id else None

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        self.auth_codes.pop(authorization_code.code, None)
        return self._mint(client.client_id, authorization_code.scopes)

    # -- refresh --
    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> Optional[RefreshToken]:
        rt = self.refresh_tokens.get(refresh_token)
        return rt if rt and rt.client_id == client.client_id else None

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: List[str]) -> OAuthToken:
        self.refresh_tokens.pop(refresh_token.token, None)
        return self._mint(client.client_id, scopes or refresh_token.scopes)

    def _mint(self, client_id: str, scopes: List[str]) -> OAuthToken:
        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        now = time.time()
        self.access_tokens[access_token] = AccessToken(
            token=access_token, client_id=client_id, scopes=scopes, expires_at=int(now + ACCESS_TOKEN_TTL_SECONDS))
        self.refresh_tokens[refresh_token] = RefreshToken(
            token=refresh_token, client_id=client_id, scopes=scopes, expires_at=int(now + REFRESH_TOKEN_TTL_SECONDS))
        return OAuthToken(access_token=access_token, token_type="Bearer",
                           expires_in=ACCESS_TOKEN_TTL_SECONDS, scope=" ".join(scopes) or None,
                           refresh_token=refresh_token)

    # -- verification --
    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        at = self.access_tokens.get(token)
        if at is None:
            return None
        if at.expires_at is not None and at.expires_at < time.time():
            del self.access_tokens[token]
            return None
        return at

    async def revoke_token(self, token) -> None:
        self.access_tokens.pop(getattr(token, "token", token), None)
        self.refresh_tokens.pop(getattr(token, "token", token), None)

def _consent_page(room_name: str, client_name: str, request_id: str, error: str = "") -> HTMLResponse:
    err_html = f'<p style="color:#b91c1c;margin:0 0 14px">{error}</p>' if error else ""
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Approve Agora access</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;background:#0b0c0f;color:#e8e8ea;
       display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
  .card{{background:#16171c;border:1px solid #2a2b32;border-radius:14px;padding:32px;max-width:400px;width:90%}}
  h1{{font-size:19px;margin:0 0 6px}}
  p.sub{{color:#9a9aa2;font-size:14px;margin:0 0 22px}}
  label{{display:block;font-size:13px;color:#c7c7cd;margin-bottom:6px}}
  input{{width:100%;box-sizing:border-box;padding:10px 12px;border-radius:8px;border:1px solid #34353d;
        background:#0f1013;color:#fff;font-size:15px;margin-bottom:16px}}
  button{{width:100%;padding:11px;border-radius:8px;border:0;background:#e8e8ea;color:#0b0c0f;
         font-size:15px;font-weight:600;cursor:pointer}}
  button:hover{{background:#fff}}
</style></head><body>
<div class="card">
  <h1>Approve access to &ldquo;{room_name}&rdquo;</h1>
  <p class="sub">{client_name or "An application"} wants to join this Agora room as a connected surface.</p>
  {err_html}
  <form method="post" action="/agora/consent">
    <input type="hidden" name="request_id" value="{request_id}">
    <label for="passphrase">Room passphrase</label>
    <input type="password" name="passphrase" id="passphrase" autofocus autocomplete="off">
    <button type="submit">Approve</button>
  </form>
</div>
</body></html>"""
    return HTMLResponse(html)

@mcp.custom_route("/agora/consent", methods=["GET", "POST"])
async def agora_consent_route(request: Request) -> HTMLResponse:
    provider = _OAUTH_PROVIDER
    if provider is None:
        return HTMLResponse("<p>OAuth is not enabled on this server.</p>", status_code=404)
    if request.method == "GET":
        request_id = request.query_params.get("request_id", "")
        entry = provider.complete_consent(request_id)
        if not entry:
            return HTMLResponse("<p>This approval link is invalid or has expired. Go back and try connecting again.</p>", status_code=400)
        client_id, _params = entry
        client = provider.clients.get(client_id)
        client_name = client.client_name if client else ""
        return _consent_page(provider.room_name, client_name, request_id)
    form = await request.form()
    request_id = str(form.get("request_id", ""))
    passphrase = str(form.get("passphrase", ""))
    entry = provider.complete_consent(request_id)
    if not entry:
        return HTMLResponse("<p>This approval link is invalid or has expired. Go back and try connecting again.</p>", status_code=400)
    client_id, _params = entry
    if not hmac.compare_digest(passphrase, provider.passphrase):
        client = provider.clients.get(client_id)
        return _consent_page(provider.room_name, client.client_name if client else "", request_id, error="Incorrect passphrase.")
    redirect_url = provider.issue_code(request_id)
    if not redirect_url:
        return HTMLResponse("<p>This approval link is invalid or has expired. Go back and try connecting again.</p>", status_code=400)
    return RedirectResponse(redirect_url, status_code=302)

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
    tags: Optional[List[str]] = Field(default_factory=list, max_length=10)

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
    artifacts: Optional[List[str]] = Field(default_factory=list, description="File paths / links produced", max_length=50)
    next_steps: Optional[List[str]] = Field(default_factory=list, max_length=50)
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
    tags: Optional[List[str]] = Field(default_factory=list, max_length=10)
    blocked_by: Optional[List[str]] = Field(default_factory=list, max_length=20)

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
                    help="Bearer token for HTTP mode (plain bearer auth), or the approval "
                         "passphrase for --oauth mode. Required when exposed beyond localhost. "
                         "Can also be set via AGORA_TOKEN env var.")
    ap.add_argument("--oauth", action="store_true",
                    help="Serve real OAuth 2.1 (Dynamic Client Registration + PKCE) instead of a "
                         "plain bearer token. Required for claude.ai / Claude Design / Claude "
                         "Chrome custom connectors, which register and authorize via OAuth, not "
                         "a static token. Requires --public-url.")
    ap.add_argument("--public-url", default=os.environ.get("AGORA_PUBLIC_URL", ""),
                    help="The public HTTPS base URL this server is reachable at (e.g. your "
                         "cloudflared/ngrok tunnel URL, no trailing slash). Required with --oauth: "
                         "start the tunnel FIRST, then pass its URL here, since OAuth metadata "
                         "must advertise the real public issuer URL.")
    args = ap.parse_args()
    if "/ABSOLUTE/PATH/TO" in args.workspace:
        ap.error(f"workspace path is an unedited placeholder ({args.workspace}). "
                 f"Set a real absolute path via --workspace or AGORA_WORKSPACE "
                 f"(or run wire-local.sh).")
    if args.oauth and not args.http:
        ap.error("--oauth requires --http.")
    if args.oauth and not args.public_url:
        ap.error("--oauth requires --public-url <https://your-tunnel-url> "
                 "(start the tunnel first, then pass its URL here).")
    STORE = AgoraStore(args.workspace, args.name)
    if args.http:
        token = args.token or None
        if args.oauth and not token:
            # Auto-generate an approval passphrase so the server is self-sufficient
            # even when run directly (not through the start-web-connector wrapper).
            token = secrets.token_urlsafe(24)
            print(f"Generated an approval passphrase (save it — you'll type it once per "
                  f"connector, at the consent screen):\n    {token}\n")
        # Refuse to start exposed-but-open: a non-loopback bind without a token/passphrase
        # would silently serve the room to anyone who can reach the port.
        if token is None and not _is_loopback(args.host):
            ap.error(f"refusing to bind {args.host} without a token. "
                     f"Set AGORA_TOKEN (or --token) before exposing beyond localhost, "
                     f"or bind --host 127.0.0.1 for local-only use.")
        mcp.settings.host = args.host
        mcp.settings.port = args.port

        # DNS-rebinding protection vs. the recommended deployment.
        #
        # FastMCP auto-enables DNS rebinding protection whenever it binds a
        # loopback host, allowing only "127.0.0.1:*"/"localhost:*" in the Host
        # header. But the correct way to expose this server is exactly that:
        # bind loopback and let a tunnel (Tailscale Funnel, cloudflared) front
        # it. Those requests arrive with the PUBLIC hostname in Host, which the
        # default allow-list rejects with 421 Misdirected Request — after OAuth
        # has fully succeeded, so the surface reports "authorized, but the
        # server returned an error" and the real cause is invisible.
        #
        # So when a public URL is declared, trust that hostname explicitly. This
        # widens the allow-list by exactly one name we were told to serve, and
        # keeps the protection intact for everything else.
        if args.public_url:
            public_host = urlparse(args.public_url).netloc
            mcp.settings.transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=[public_host, f"{public_host}:*",
                               "127.0.0.1:*", "localhost:*", "[::1]:*"],
                allowed_origins=[args.public_url, f"{args.public_url}:*",
                                 "http://127.0.0.1:*", "http://localhost:*"],
            )

        if args.oauth:
            global _OAUTH_PROVIDER
            provider = AgoraOAuthProvider(passphrase=token, public_url=args.public_url, room_name=args.name)
            _OAUTH_PROVIDER = provider
            mcp._auth_server_provider = provider
            mcp._token_verifier = ProviderTokenVerifier(provider)
            mcp.settings.auth = AuthSettings(
                issuer_url=AnyHttpUrl(args.public_url),
                client_registration_options=ClientRegistrationOptions(enabled=True),
                revocation_options=RevocationOptions(enabled=True),
                resource_server_url=AnyHttpUrl(f"{args.public_url}{mcp.settings.streamable_http_path}"),
            )
            print(f"Agora MCP HTTP on http://{args.host}:{args.port}  (public: {args.public_url})")
            print(f"Auth: OAuth 2.1 — clients self-register, humans approve at {args.public_url}/agora/consent")
            print(f"Custom connector URL for claude.ai / Design / Chrome:  {args.public_url}{mcp.settings.streamable_http_path}")
            mcp.run(transport="streamable-http")
        elif token:
            # Plain bearer-token mode (no OAuth dance) — simplest path for
            # non-browser clients or same-machine testing.
            import uvicorn
            from starlette.middleware.base import BaseHTTPMiddleware
            from starlette.responses import JSONResponse

            class BearerAuthMiddleware(BaseHTTPMiddleware):
                async def dispatch(self, request, call_next):
                    auth = request.headers.get("Authorization", "")
                    if not hmac.compare_digest(auth, f"Bearer {token}"):
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
