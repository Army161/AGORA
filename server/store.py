"""Agora workspace store — shared coordination state every Claude surface reads/writes.

Pure stdlib (no deps) so it is importable and testable anywhere. agora_mcp.py is a
thin MCP wrapper over this class.

Concurrency: one cross-process mutex (atomically-created lock dir) guards each
mutation (brief read-modify-write-append). JSON writes are atomic (temp + os.replace).
Agents coordinate via leases (TTL) on tasks/locks plus an append-only event log.
"""
from __future__ import annotations
import json, os, time, tempfile, shutil
from datetime import datetime, timezone
from typing import Any, Optional

PRESENCE_ACTIVE_SECONDS = 600
DEFAULT_LEASE_MINUTES = 30
MUTEX_STALE_SECONDS = 30
MUTEX_TIMEOUT_SECONDS = 10
SURFACES = {"claude_ai", "cowork", "claude_code", "chrome", "design", "other"}
TASK_STATES = {"todo", "in_progress", "blocked", "review", "done"}

def _now() -> float: return time.time()
def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

class _Mutex:
    def __init__(self, path: str): self.path = path
    def __enter__(self):
        start = time.time()
        while True:
            try:
                os.mkdir(self.path); return self
            except FileExistsError:
                try: age = time.time() - os.path.getmtime(self.path)
                except OSError: age = 0
                if age > MUTEX_STALE_SECONDS:
                    shutil.rmtree(self.path, ignore_errors=True); continue
                if time.time() - start > MUTEX_TIMEOUT_SECONDS:
                    raise TimeoutError("Could not acquire Agora workspace lock")
                time.sleep(0.05)
    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True); return False

class AgoraStore:
    def __init__(self, root: str, name: str = "Agora Workspace"):
        self.root = os.path.abspath(os.path.expanduser(root))
        self.name = name
        self.lockdir = os.path.join(self.root, ".lock")
        os.makedirs(self.root, exist_ok=True)

    # ---------- low-level ----------
    def _path(self, *p): return os.path.join(self.root, *p)
    # Every file handle below pins encoding="utf-8" explicitly. Without it Python
    # uses the platform default — cp1252 on a typical Windows box — which cannot
    # encode emoji, CJK or Cyrillic. An agent posting "shipped 🚀" would raise
    # UnicodeEncodeError and fail the whole call, and a workspace written on
    # Windows would not read back correctly on macOS or Linux.
    def _atomic_write(self, path: str, text: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
        with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(text)
        os.replace(tmp, path)
    def _load(self, name: str, default: Any):
        p = self._path(name)
        if not os.path.exists(p): return default
        with open(p, encoding="utf-8") as f: return json.load(f)
    def _save(self, name: str, obj: Any):
        self._atomic_write(self._path(name), json.dumps(obj, indent=2))
    def _mutex(self): return _Mutex(self.lockdir)

    def _ensure(self):
        """Bootstrap the workspace. Caller must hold the mutex."""
        if os.path.exists(self._path("meta.json")): return
        for d in ("handoffs", "updates", "messages"):
            os.makedirs(self._path(d), exist_ok=True)
        meta = {"workspace": self.name, "created_at": _iso(_now()),
                "event_seq": 0, "task_seq": 0, "handoff_seq": 0,
                "update_seq": 0, "message_seq": 0}
        self._save("meta.json", meta)
        self._save("agents.json", {})
        self._save("tasks.json", {})
        self._save("locks.json", {})
        self._save("memory.json", {"pinned": [], "style": {"voice": "", "format": "", "citations": "", "maxlen": ""}})
        open(self._path("events.jsonl"), "a").close()
        self._atomic_write(self._path("updates", "UPDATES.md"),
                           f"# Updates feed — {self.name}\n\n")
        self._atomic_write(self._path("AGENTS.md"), _AGENTS_MD.format(name=self.name))
        self._render_board(meta)

    def _ensure_safe(self):
        """Bootstrap the workspace holding the mutex (safe to call from outside)."""
        with self._mutex():
            self._ensure()

    def _next_id(self, meta, key, prefix):
        meta[key] += 1
        return f"{prefix}-{meta[key]:04d}"

    def _append_event(self, meta, kind, actor, summary, data=None):
        meta["event_seq"] += 1
        rec = {"seq": meta["event_seq"], "ts": _now(), "at": _iso(_now()),
               "kind": kind, "actor": actor, "summary": summary, "data": data or {}}
        with open(self._path("events.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        return rec

    def _read_events(self, since_seq=0, limit=50):
        out = []
        p = self._path("events.jsonl")
        if not os.path.exists(p): return out
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                r = json.loads(line)
                if r["seq"] > since_seq: out.append(r)
        return out[-limit:]

    def _presence(self, agent):
        idle = _now() - agent.get("last_seen", 0)
        if agent.get("status") == "left": return "left"
        return "active" if idle <= PRESENCE_ACTIVE_SECONDS else "away"

    # ---------- presence ----------
    def join(self, agent_id, surface, role="", display_name=""):
        if surface not in SURFACES: surface = "other"
        with self._mutex():
            self._ensure()
            meta = self._load("meta.json", {})
            agents = self._load("agents.json", {})
            existing = agents.get(agent_id, {})
            agents[agent_id] = {
                "agent_id": agent_id, "surface": surface,
                "role": role or existing.get("role", ""),
                "display_name": display_name or existing.get("display_name", agent_id),
                "joined_at": existing.get("joined_at", _iso(_now())),
                "last_seen": _now(), "status": "active",
                "current": existing.get("current", "")}
            self._save("agents.json", agents)
            self._append_event(meta, "join", agent_id,
                               f"{agent_id} ({surface}) joined" + (f" as {role}" if role else ""))
            self._save("meta.json", meta)
            self._render_board(meta)
            return self.summary(for_agent=agent_id)

    def summary(self, for_agent=None):
        agents = self._load("agents.json", {})
        tasks = self._load("tasks.json", {})
        locks = self._load("locks.json", {})
        handoffs = self._load("handoffs/index.json", [])
        return {
            "workspace": self._load("meta.json", {}).get("workspace", self.name),
            "agents": [{**a, "presence": self._presence(a)} for a in agents.values()],
            "tasks": list(tasks.values()),
            "locks": locks,
            "open_handoffs": [h for h in handoffs if h["status"] != "done"
                              and (for_agent is None or h["to"] in (for_agent, "any"))],
            "recent_events": self._read_events(limit=15),
        }

    # ---------- updates ----------
    def post_update(self, agent_id, message, task_id=None, tags=None):
        with self._mutex():
            self._ensure()
            meta = self._load("meta.json", {})
            uid = self._next_id(meta, "update_seq", "U")
            rec = {"id": uid, "agent": agent_id, "message": message,
                   "task_id": task_id, "tags": tags or [], "at": _iso(_now())}
            idx = self._load("updates/index.json", [])
            idx.append(rec); self._save("updates/index.json", idx)
            with open(self._path("updates", "UPDATES.md"), "a", encoding="utf-8") as f:
                tg = f"  _{', '.join(tags)}_" if tags else ""
                tk = f" (task {task_id})" if task_id else ""
                f.write(f"- **{rec['at']}** — `{agent_id}`{tk}: {message}{tg}\n")
            self._touch(agents_id=agent_id, current=message)
            self._append_event(meta, "update", agent_id, message, {"id": uid, "task_id": task_id})
            self._save("meta.json", meta); self._render_board(meta)
            return rec

    def _touch(self, agents_id, current=None):
        agents = self._load("agents.json", {})
        if agents_id in agents:
            agents[agents_id]["last_seen"] = _now()
            if current is not None: agents[agents_id]["current"] = current[:140]
            self._save("agents.json", agents)

    # ---------- handoffs ----------
    def create_handoff(self, from_agent, to_agent, title, summary, context="",
                       artifacts=None, next_steps=None, task_id=None):
        with self._mutex():
            self._ensure()
            meta = self._load("meta.json", {})
            hid = self._next_id(meta, "handoff_seq", "H")
            rec = {"id": hid, "from": from_agent, "to": to_agent or "any",
                   "title": title, "status": "open", "summary": summary, "task_id": task_id,
                   "created_at": _iso(_now()), "file": f"handoffs/{hid}.md",
                   "log": []}
            md = _HANDOFF_MD.format(
                id=hid, title=title, frm=from_agent, to=rec["to"],
                created=rec["created_at"], task=task_id or "—", summary=summary,
                context=context or "—",
                artifacts="\n".join(f"- {a}" for a in (artifacts or [])) or "- —",
                next_steps="\n".join(f"- [ ] {s}" for s in (next_steps or [])) or "- —")
            self._atomic_write(self._path("handoffs", f"{hid}.md"), md)
            idx = self._load("handoffs/index.json", [])
            idx.append(rec); self._save("handoffs/index.json", idx)
            self._append_event(meta, "handoff", from_agent,
                               f"handoff {hid} {from_agent}->{rec['to']}: {title}",
                               {"id": hid, "to": rec["to"]})
            self._save("meta.json", meta); self._render_board(meta)
            return rec

    def list_handoffs(self, for_agent=None, status=None, limit=20):
        idx = self._load("handoffs/index.json", [])
        out = []
        for h in idx:
            if status and h["status"] != status: continue
            if for_agent and h["to"] not in (for_agent, "any") and h["from"] != for_agent: continue
            out.append(h)
        return out[-limit:]

    def _update_handoff(self, handoff_id, agent_id, new_status, note, kind):
        with self._mutex():
            self._ensure()
            meta = self._load("meta.json", {})
            idx = self._load("handoffs/index.json", [])
            found = None
            for h in idx:
                if h["id"] == handoff_id:
                    h["status"] = new_status
                    h.setdefault("log", []).append(
                        {"by": agent_id, "at": _iso(_now()), "status": new_status, "note": note})
                    found = h; break
            if not found:
                return {"error": f"handoff {handoff_id} not found"}
            self._save("handoffs/index.json", idx)
            self._touch(agent_id)
            self._append_event(meta, kind, agent_id,
                               f"{handoff_id} -> {new_status} by {agent_id}", {"id": handoff_id})
            self._save("meta.json", meta); self._render_board(meta)
            return found

    def ack_handoff(self, handoff_id, agent_id, note=""):
        return self._update_handoff(handoff_id, agent_id, "acked", note, "handoff_ack")
    def complete_handoff(self, handoff_id, agent_id, result=""):
        return self._update_handoff(handoff_id, agent_id, "done", result, "handoff_done")

    # ---------- tasks ----------
    def add_task(self, title, created_by, description="", tags=None, blocked_by=None):
        with self._mutex():
            self._ensure()
            meta = self._load("meta.json", {})
            tid = self._next_id(meta, "task_seq", "T")
            tasks = self._load("tasks.json", {})
            tasks[tid] = {"id": tid, "title": title, "description": description,
                          "status": "todo", "owner": None, "lease_until": 0,
                          "created_by": created_by, "tags": tags or [],
                          "blocked_by": blocked_by or [], "created_at": _iso(_now()),
                          "updated_at": _iso(_now())}
            self._save("tasks.json", tasks)
            self._append_event(meta, "task_add", created_by, f"{tid}: {title}", {"id": tid})
            self._save("meta.json", meta); self._render_board(meta)
            return tasks[tid]

    def claim_task(self, task_id, agent_id, ttl_minutes=DEFAULT_LEASE_MINUTES, force=False):
        with self._mutex():
            self._ensure()
            meta = self._load("meta.json", {})
            tasks = self._load("tasks.json", {})
            t = tasks.get(task_id)
            if not t: return {"error": f"task {task_id} not found"}
            if t["owner"] and t["owner"] != agent_id and t["lease_until"] > _now() and not force:
                return {"error": f"task {task_id} is owned by {t['owner']} until "
                                 f"{_iso(t['lease_until'])}. Use force=true to override."}
            t["owner"] = agent_id; t["status"] = "in_progress"
            t["lease_until"] = _now() + ttl_minutes * 60; t["updated_at"] = _iso(_now())
            self._save("tasks.json", tasks); self._touch(agent_id, current=f"task {task_id}: {t['title']}")
            self._append_event(meta, "task_claim", agent_id, f"{agent_id} claimed {task_id}", {"id": task_id})
            self._save("meta.json", meta); self._render_board(meta)
            return t

    def update_task(self, task_id, agent_id, status=None, note="", extend_minutes=None):
        with self._mutex():
            self._ensure()
            meta = self._load("meta.json", {})
            tasks = self._load("tasks.json", {})
            t = tasks.get(task_id)
            if not t: return {"error": f"task {task_id} not found"}
            if status:
                if status not in TASK_STATES:
                    return {"error": f"invalid status. Use one of {sorted(TASK_STATES)}"}
                t["status"] = status
                if status == "done": t["owner"] = None; t["lease_until"] = 0
            if extend_minutes: t["lease_until"] = _now() + extend_minutes * 60
            t["updated_at"] = _iso(_now())
            self._save("tasks.json", tasks); self._touch(agent_id)
            self._append_event(meta, "task_update", agent_id,
                               f"{task_id} -> {t['status']}" + (f": {note}" if note else ""),
                               {"id": task_id})
            self._save("meta.json", meta); self._render_board(meta)
            return t

    def release_task(self, task_id, agent_id):
        return self.update_task(task_id, agent_id, status="todo", note="released")

    # ---------- locks ----------
    def lock_resource(self, resource, agent_id, ttl_minutes=DEFAULT_LEASE_MINUTES, note="", force=False):
        with self._mutex():
            self._ensure()
            meta = self._load("meta.json", {})
            locks = self._load("locks.json", {})
            cur = locks.get(resource)
            if cur and cur["holder"] != agent_id and cur["lease_until"] > _now() and not force:
                return {"error": f"{resource} locked by {cur['holder']} until {_iso(cur['lease_until'])}. "
                                 f"Use force=true to override."}
            locks[resource] = {"holder": agent_id, "acquired_at": _iso(_now()),
                               "lease_until": _now() + ttl_minutes * 60, "note": note}
            self._save("locks.json", locks); self._touch(agent_id)
            self._append_event(meta, "lock", agent_id, f"{agent_id} locked {resource}", {"resource": resource})
            self._save("meta.json", meta); self._render_board(meta)
            return locks[resource]

    def unlock_resource(self, resource, agent_id):
        with self._mutex():
            self._ensure()
            meta = self._load("meta.json", {})
            locks = self._load("locks.json", {})
            if resource in locks: del locks[resource]
            self._save("locks.json", locks); self._touch(agent_id)
            self._append_event(meta, "unlock", agent_id, f"{agent_id} released {resource}", {"resource": resource})
            self._save("meta.json", meta); self._render_board(meta)
            return {"resource": resource, "released": True}

    # ---------- messages ----------
    def send_message(self, from_agent, to_agent, body):
        with self._mutex():
            self._ensure()
            meta = self._load("meta.json", {})
            mid = self._next_id(meta, "message_seq", "M")
            msgs = self._load("messages/index.json", [])
            rec = {"id": mid, "from": from_agent, "to": to_agent or "all",
                   "body": body, "at": _iso(_now()), "read_by": []}
            msgs.append(rec); self._save("messages/index.json", msgs)
            self._touch(from_agent)
            self._append_event(meta, "message", from_agent,
                               f"{from_agent}->{rec['to']}: {body[:60]}", {"id": mid})
            self._save("meta.json", meta)
            return rec

    def get_messages(self, agent_id, limit=20):
        msgs = self._load("messages/index.json", [])
        out = [m for m in msgs if m["to"] in (agent_id, "all") or m["from"] == agent_id]
        return out[-limit:]

    def events(self, since_seq=0, limit=50):
        return self._read_events(since_seq=since_seq, limit=limit)

    # ---------- shared memory ----------
    def get_memory(self):
        with self._mutex():
            self._ensure()
            return self._load("memory.json", {"pinned": [], "style": {}})

    def add_pin(self, text, by):
        with self._mutex():
            self._ensure()
            meta = self._load("meta.json", {})
            mem = self._load("memory.json", {"pinned": [], "style": {}})
            pid = f"P-{len(mem['pinned'])+1:04d}"
            mem["pinned"].insert(0, {"id": pid, "text": text, "by": by, "at": _iso(_now())})
            self._save("memory.json", mem)
            self._append_event(meta, "pin", by, f"{by} pinned a fact")
            self._save("meta.json", meta); self._render_board(meta)
            return mem

    def set_style(self, style):
        with self._mutex():
            self._ensure()
            meta = self._load("meta.json", {})
            mem = self._load("memory.json", {"pinned": [], "style": {}})
            for k in ("voice", "format", "citations", "maxlen"):
                if style.get(k) is not None:
                    mem["style"][k] = style[k]
            self._save("memory.json", mem)
            self._append_event(meta, "style", "house", "house style updated")
            self._save("meta.json", meta)
            return mem

    # ---------- board render ----------
    def _render_board(self, meta):
        agents = self._load("agents.json", {})
        tasks = self._load("tasks.json", {})
        locks = self._load("locks.json", {})
        handoffs = self._load("handoffs/index.json", [])
        L = [f"# Agora Board — {meta.get('workspace', self.name)}",
             f"_rendered {_iso(_now())}_\n", "## Agents"]
        if agents:
            for a in agents.values():
                L.append(f"- `{a['agent_id']}` [{self._presence(a)}] {a['surface']}"
                         f"{(' / ' + a['role']) if a.get('role') else ''}"
                         f"{(' — ' + a['current']) if a.get('current') else ''}")
        else: L.append("- (none yet)")
        L.append("\n## Tasks")
        if tasks:
            for t in tasks.values():
                own = f" @{t['owner']}" if t["owner"] else ""
                L.append(f"- [{t['status']}] {t['id']} {t['title']}{own}")
        else: L.append("- (none yet)")
        live = {r: v for r, v in locks.items() if v["lease_until"] > _now()}
        if live:
            L.append("\n## Active locks")
            for r, v in live.items(): L.append(f"- {r} — @{v['holder']}")
        opn = [h for h in handoffs if h["status"] != "done"]
        if opn:
            L.append("\n## Open handoffs")
            for h in opn: L.append(f"- {h['id']} {h['from']}->{h['to']}: {h['title']} [{h['status']}]")
        L.append("\n## Recent activity")
        for e in self._read_events(limit=12): L.append(f"- {e['at']} — {e['summary']}")
        self._atomic_write(self._path("board.md"), "\n".join(L) + "\n")

_AGENTS_MD = """# Agora — Operating Manual ({name})

This workspace is a shared meeting room for multiple Claude surfaces
(claude.ai, Cowork, Claude Code, Chrome, Design). Coordinate here.

## On arrival
1. Call `agora_join` with your agent_id, surface, role.
2. Read the returned summary (agents, open tasks, handoffs for you, recent events).

## While working
- Take work with `agora_claim_task` before starting (prevents collisions).
- Lock files you edit with `agora_lock_resource`; unlock when done.
- Post progress with `agora_post_update`.
- Hand work to another agent with `agora_create_handoff`; they `agora_ack_handoff` then `agora_complete_handoff`.
- Direct/broadcast notes via `agora_send_message`.

## Conventions
- One task = one owner at a time (leased). Release or complete when done.
- Never edit a locked resource you don't hold.
- Keep updates short and factual.
"""

_HANDOFF_MD = """# Handoff {id}: {title}

- From: {frm}
- To: {to}
- Created: {created}
- Related task: {task}
- Status: open

## Summary
{summary}

## Context
{context}

## Artifacts
{artifacts}

## Next steps
{next_steps}
"""
