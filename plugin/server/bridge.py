"""Agora live bridge — connects the dashboard (and any HTTP client) to the real .agora room.

It reads the workspace through the same AgoraStore the MCP server uses (one source of
truth), serves a dashboard-shaped /state snapshot, applies /act actions, and can serve the
dashboard itself so everything is same-origin (no CORS headaches).

Run:
    python bridge.py --workspace ~/projects/app/.agora --port 8849 [--seed]
Then open http://localhost:8849  (or open the standalone dashboard; it auto-detects this).

Read-only by default? No — it performs coordination writes via the store. Add an auth
token before exposing it beyond localhost (see HANDOFF.md).
"""
import argparse, hmac, json, os, sys, time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import AgoraStore

STORE = None
DASHBOARD = None
TOKEN = None   # set via --token; if set, /state and /act require Authorization: Bearer <token>

def _is_loopback(host):
    """True only for hosts that are unreachable from other machines.
    Note: "" / "0.0.0.0" / "::" bind to ALL interfaces — never loopback."""
    return host in ("127.0.0.1", "localhost", "::1")
SETTINGS_DEFAULT = {
    "theme": "dark", "density": "comfortable", "autoroute": True,
    "rules": [
        {"tag": "frontend", "surface": "claude_code"}, {"tag": "build", "surface": "claude_code"},
        {"tag": "design", "surface": "design"}, {"tag": "copy", "surface": "cowork"},
        {"tag": "ia", "surface": "cowork"}, {"tag": "research", "surface": "claude_ai"},
        {"tag": "browser", "surface": "chrome"}, {"tag": "qa", "surface": "chrome"},
    ],
}

def iso2ms(s):
    try:
        return int(datetime.strptime(s, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc).timestamp() * 1000)
    except Exception:
        return int(time.time() * 1000)

def settings_path():
    return os.path.join(STORE.root, "dashboard.json")

def load_settings():
    p = settings_path()
    s = dict(SETTINGS_DEFAULT)
    if os.path.exists(p):
        try:
            s.update(json.load(open(p, encoding="utf-8")))
        except Exception:
            pass
    s["workspace"] = STORE.root
    return s

def save_settings(s):
    keep = {k: s.get(k, SETTINGS_DEFAULT.get(k)) for k in ("theme", "density", "autoroute", "rules")}
    STORE._atomic_write(settings_path(), json.dumps(keep, indent=2))

def shape_state():
    STORE._ensure_safe()
    agents_raw = STORE._load("agents.json", {})
    tasks_raw = STORE._load("tasks.json", {})
    settings = load_settings()
    def load_of(aid):
        return len([1 for t in tasks_raw.values() if t.get("owner") == aid and t.get("status") != "done"])
    agents = [{
        "id": a["agent_id"], "name": a.get("display_name") or a["agent_id"], "surface": a["surface"],
        "role": a.get("role", ""), "presence": STORE._presence(a),
        "current": a.get("current") or "idle", "load": load_of(a["agent_id"]),
    } for a in agents_raw.values()]
    tasks = [{
        "id": t["id"], "title": t["title"], "status": t["status"], "owner": t.get("owner"),
        "lease_until": int(t["lease_until"] * 1000) if t.get("lease_until") else 0,
        "tags": t.get("tags", []), "created_by": t.get("created_by"),
        "created_at": iso2ms(t.get("created_at", "")),
    } for t in tasks_raw.values()]
    handoffs = [{
        "id": h["id"], "from": h["from"], "to": h["to"], "title": h["title"],
        "status": h["status"], "summary": h.get("summary", ""), "created_at": iso2ms(h.get("created_at", "")),
    } for h in STORE._load("handoffs/index.json", [])]
    updates = [{
        "id": u["id"], "agent": u["agent"], "message": u["message"],
        "task_id": u.get("task_id"), "at": iso2ms(u.get("at", "")),
    } for u in STORE._load("updates/index.json", [])]
    messages = [{
        "id": m["id"], "from": m["from"], "to": m["to"], "body": m["body"], "at": iso2ms(m.get("at", "")),
    } for m in STORE._load("messages/index.json", [])]
    events = [{
        "seq": e["seq"], "kind": e["kind"], "actor": e["actor"], "summary": e["summary"],
        "at": int(e.get("ts", 0) * 1000) or iso2ms(e.get("at", "")),
    } for e in STORE._read_events(limit=200)]
    mem = STORE.get_memory()
    memory = {
        "pinned": [{"id": p.get("id"), "text": p["text"], "by": p["by"], "at": iso2ms(p.get("at", ""))} for p in mem.get("pinned", [])],
        "style": {k: mem.get("style", {}).get(k, "") for k in ("voice", "format", "citations", "maxlen")},
    }
    return {"agents": agents, "tasks": tasks, "handoffs": handoffs, "updates": updates,
            "messages": messages, "events": events, "memory": memory, "settings": settings}

def route(task_id):
    tasks = STORE._load("tasks.json", {}); t = tasks.get(task_id)
    if not t or t.get("owner"):
        return None
    settings = load_settings()
    agents = list(STORE._load("agents.json", {}).values())
    surf = None
    for tag in t.get("tags", []):
        for r in settings.get("rules", []):
            if r.get("tag") == tag:
                surf = r.get("surface"); break
        if surf:
            break
    cand = [a for a in agents if STORE._presence(a) != "left" and a["agent_id"] != "claude" and (a["surface"] == surf if surf else True)]
    if not cand:
        cand = [a for a in agents if a["agent_id"] != "claude"] or agents
    if not cand:
        return None
    def ld(a):
        return len([1 for x in tasks.values() if x.get("owner") == a["agent_id"] and x.get("status") != "done"])
    cand.sort(key=ld)
    STORE.claim_task(task_id, cand[0]["agent_id"], force=True)
    return cand[0]["agent_id"]

def apply_action(action, p):
    p = p or {}
    if action == "add_task":
        t = STORE.add_task(p["title"], p.get("by", "dashboard"), p.get("description", ""), p.get("tags", []))
        if load_settings().get("autoroute"):
            route(t["id"])
        return t
    if action == "route_task":
        return {"routed_to": route(p["id"])}
    if action == "route_all":
        todo = [t["id"] for t in STORE._load("tasks.json", {}).values() if not t.get("owner") and t.get("status") == "todo"]
        return {"routed": [route(i) for i in todo]}
    if action == "task_done":
        return STORE.update_task(p["id"], p.get("by", "dashboard"), status="done")
    if action == "assign":
        tid = p.get("id")
        if not tid:
            todo = [t for t in STORE._load("tasks.json", {}).values() if not t.get("owner") and t.get("status") == "todo"]
            if not todo:
                return {"error": "no open tasks"}
            tid = todo[0]["id"]
        return STORE.claim_task(tid, p["agent"], force=True)
    if action == "message":
        return STORE.send_message(p.get("from", "dashboard"), p.get("to", "all"), p["body"])
    if action == "handoff":
        return STORE.create_handoff(p.get("from", "dashboard"), p.get("to", "any"), p["title"], p.get("summary", ""),
                                    p.get("context", ""), p.get("artifacts", []), p.get("next_steps", []))
    if action == "pin":
        return STORE.add_pin(p["text"], p.get("by", "dashboard"))
    if action == "set_style":
        return STORE.set_style(p.get("style", {}))
    if action == "set_settings":
        save_settings(p.get("settings", {}))
        return load_settings()
    return {"error": "unknown action " + str(action)}

class H(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
    def _json(self, obj, code=200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(code); self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def _auth_ok(self):
        """Return True if no token is configured or the request carries the right one."""
        if not TOKEN:
            return True
        auth = self.headers.get("Authorization", "")
        return hmac.compare_digest(auth, f"Bearer {TOKEN}")
    def log_message(self, *a):
        pass
    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html") and DASHBOARD and os.path.exists(DASHBOARD):
            body = open(DASHBOARD, "rb").read()
            self.send_response(200); self._cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body); return
        if path == "/health":
            return self._json({"ok": True, "workspace": STORE.root})
        if path == "/state":
            if not self._auth_ok():
                return self._json({"error": "unauthorized"}, 401)
            try:
                return self._json(shape_state())
            except Exception as e:
                return self._json({"error": str(e)}, 500)
        self._json({"error": "not found"}, 404)
    def do_POST(self):
        if self.path.split("?")[0] != "/act":
            return self._json({"error": "not found"}, 404)
        if not self._auth_ok():
            return self._json({"error": "unauthorized"}, 401)
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
            res = apply_action(data.get("action"), data.get("payload"))
            return self._json({"ok": True, "result": res})
        except Exception as e:
            return self._json({"ok": False, "error": str(e)}, 400)

def seed_workspace():
    if STORE._load("agents.json", {}):
        return  # already populated
    S = STORE
    S.join("claude", "claude", "Orchestrator", "Claude")
    S.join("code-1", "claude_code", "Builder", "Claude Code")
    S.join("cowork-1", "cowork", "Strategist", "Claude Co-Pilot")
    S.join("design-1", "design", "Designer", "Claude Design")
    S.join("chat-1", "claude_ai", "Researcher", "Claude Chat")
    S.join("chrome-1", "chrome", "Operator", "Claude Browser")
    t1 = S.add_task("Information architecture + hero copy", "claude", tags=["copy", "ia"])
    t2 = S.add_task("Build responsive hero section", "claude", tags=["frontend", "build"])
    t3 = S.add_task("Visual system: color, type, spacing tokens", "claude", tags=["design"])
    S.add_task("Wire CTA form + analytics events", "claude", tags=["frontend", "build"])
    S.add_task("QA pass across breakpoints", "claude", tags=["qa", "browser"])
    S.claim_task(t1["id"], "cowork-1"); S.claim_task(t2["id"], "code-1"); S.claim_task(t3["id"], "design-1")
    S.post_update("design-1", "Published spacing scale + clay accent", t3["id"])
    S.post_update("code-1", "Hero markup scaffolded", t2["id"])
    S.create_handoff("design-1", "code-1", "Hero tokens ready", "Color + type + spacing tokens published; use --accent for the primary CTA.")
    S.add_pin("Goal: landing page led by the time-saved metric.", "claude")
    S.set_style({"voice": "Warm, plain, confident — no hype words", "format": "Sentence case. Short sentences.",
                 "citations": "Link claims to the competitor scan", "maxlen": "Hero headline <= 9 words"})

def main():
    global STORE, DASHBOARD, TOKEN
    ap = argparse.ArgumentParser(description="Agora live bridge (dashboard <-> .agora workspace)")
    ap.add_argument("--workspace", default=os.environ.get("AGORA_WORKSPACE", "~/.agora/default"))
    ap.add_argument("--name", default=os.environ.get("AGORA_NAME", "Agora Workspace"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8849)
    ap.add_argument("--seed", action="store_true", help="Seed a starter scenario if the room is empty")
    ap.add_argument("--dashboard", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dashboard", "index.html"))
    ap.add_argument("--token", default=os.environ.get("AGORA_TOKEN", ""),
                    help="Bearer token for /state and /act. Required when exposed beyond localhost. "
                         "Can also be set via AGORA_TOKEN env var.")
    args = ap.parse_args()
    if "/ABSOLUTE/PATH/TO" in args.workspace:
        ap.error(f"workspace path is an unedited placeholder ({args.workspace}). "
                 f"Set a real absolute path via --workspace or AGORA_WORKSPACE "
                 f"(or run wire-local.sh).")
    TOKEN = args.token or None
    # Refuse to start exposed-but-open: a non-loopback bind without a token
    # would silently serve /state and /act to anyone who can reach the port.
    if TOKEN is None and not _is_loopback(args.host):
        ap.error(f"refusing to bind {args.host} without a token. "
                 f"Set AGORA_TOKEN (or --token) before exposing beyond localhost, "
                 f"or bind --host 127.0.0.1 for local-only use.")
    STORE = AgoraStore(args.workspace, args.name)
    STORE._ensure_safe()
    DASHBOARD = os.path.abspath(args.dashboard) if args.dashboard and os.path.exists(args.dashboard) else None
    if args.seed:
        seed_workspace()
    srv = ThreadingHTTPServer((args.host, args.port), H)
    print(f"Agora bridge on http://{args.host}:{args.port}  workspace={STORE.root}")
    if TOKEN:
        print(f"Auth:  Authorization: Bearer {TOKEN}")
    else:
        print("Auth:  none (localhost-only is fine; use --token before exposing publicly)")
    if DASHBOARD:
        print(f"Open http://{args.host}:{args.port}  (serving dashboard)")
    srv.serve_forever()

if __name__ == "__main__":
    main()
