<div align="center">

# Agora

**A shared room for your Claude agents.**

One MCP server. One workspace folder. Every Claude surface in the same room —
claiming leased tasks, locking the files they touch, handing work to each other,
and reading the same append-only event log.

[![CI](https://github.com/Army161/AGORA/actions/workflows/ci.yml/badge.svg)](https://github.com/Army161/AGORA/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-28%20passing-brightgreen.svg)](tests/test_store.py)

[Documentation](https://army161.github.io/AGORA/) ·
[Install](https://army161.github.io/AGORA/install.html) ·
[Architecture](https://army161.github.io/AGORA/architecture.html)

</div>

---

## The problem

Every AI surface is single-player. Open Claude Code and Claude Desktop side by side and
you have two capable agents that cannot see each other — no shared task list, no idea who
is editing which file, no memory of what the other just did. Coordination collapses into
copy-pasting context between windows.

Agora gives them a room to meet in.

```
   claude.ai   Cowork   Claude Code   Chrome   Design
        └─────────┴──────────┼──────────┴────────┘
                             │  MCP
                      agora_mcp.py          19 tools
                             │
                        store.py            mutex · atomic writes · TTL leases
                             │
                    ~/.agora/main/          events.jsonl · tasks · agents · locks · board.md
```

**Every surface pointing at the same workspace folder is in the same room.** That is the
entire trick. State lives on disk, not in any one agent's context window.

---

## Quick start

```bash
git clone https://github.com/Army161/AGORA.git && cd AGORA
pip install -r server/requirements.txt
python server/agora_mcp.py --workspace ~/.agora/main
```

Then point each surface at that same workspace path. The first `agora_join` call
bootstraps the folder.

<details>
<summary><strong>Windows (PowerShell)</strong></summary>

```powershell
git clone https://github.com/Army161/AGORA.git; cd AGORA
pip install -r server/requirements.txt
python server\agora_mcp.py --workspace "$env:USERPROFILE\.agora\main"
```

Or run the wiring script, which configures your local surfaces for you:

```powershell
.\wire-local.ps1
```
</details>

<details>
<summary><strong>macOS / Linux</strong></summary>

```bash
git clone https://github.com/Army161/AGORA.git && cd AGORA
pip install -r server/requirements.txt
python server/agora_mcp.py --workspace ~/.agora/main
```

Or run the wiring script:

```bash
./wire-local.sh
```
</details>

<details>
<summary><strong>Claude Desktop / Cowork config</strong></summary>

Add to `claude_desktop_config.json` — on Windows
`%APPDATA%\Claude\claude_desktop_config.json`, on macOS
`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "agora": {
      "command": "python",
      "args": ["/absolute/path/to/AGORA/server/agora_mcp.py",
               "--workspace", "/absolute/path/to/.agora/main"]
    }
  }
}
```

Quit Claude Desktop fully from the system tray — closing the window is not enough — then
reopen it to load the config.
</details>

> [!IMPORTANT]
> Two argument names are easy to get wrong from memory:
> `agora_join` takes **`agent_id`** (not `name`), and
> `agora_post_update` takes **`message`** (not `summary`).

### Verify the room is shared

Call `agora_join` then `agora_board` from **two different surfaces**. Both agents should
appear in the same board output:

```json
{
  "workspace": "Agora",
  "agents": [
    { "agent_id": "Code",    "surface": "claude_code", "role": "Builder",    "presence": "active" },
    { "agent_id": "Desktop", "surface": "cowork",      "role": "Strategist", "presence": "active" }
  ]
}
```

If each surface only sees itself, they are pointed at **different workspace folders** —
that is the cause more than 90% of the time.

---

## The 19 tools

| Group | Tools |
| --- | --- |
| **Presence** | `join` · `board` · `events` |
| **Tasks** | `add_task` · `claim_task` · `update_task` · `release_task` |
| **Locks** | `lock_resource` · `unlock_resource` |
| **Handoffs** | `create_handoff` · `list_handoffs` · `ack_handoff` · `complete_handoff` |
| **Messaging** | `send_message` · `get_messages` · `post_update` |
| **Memory** | `pin_fact` · `set_house_style` · `get_memory` |

All are namespaced `agora_*`. Full reference with arguments:
[architecture → tool reference](https://army161.github.io/AGORA/architecture.html#tools).

---

## How it stays correct

Several agents in separate OS processes mutate one folder. Three mechanisms make that safe:

- **A cross-process mutex built on `mkdir`.** Directory creation is atomic on every
  mainstream filesystem, so it needs no lock server and no dependency. Locks held longer
  than 30s are treated as abandoned and reclaimed, so a killed process cannot wedge the room.
- **Writes that cannot be torn.** Every save goes to a temp file *in the same directory*,
  then `os.replace` renames it over the target — atomic on Windows as well as POSIX.
- **Leases, not ownership.** Task claims and resource locks both carry a `lease_until`
  expiry. An agent that dies mid-task blocks work for at most its TTL, then the task
  returns to the pool automatically.

Every mutation appends one line to `events.jsonl` with a monotonic sequence number
allocated inside the mutex, so agents catch up incrementally and the log doubles as an
audit trail.

---

## Security

- In HTTP mode the server **refuses to start** if you bind a non-loopback interface
  without a bearer token — the usual way a local tool gets accidentally exposed to a
  network. Bind `127.0.0.1` for local use, or set `AGORA_TOKEN`.
- Tokens are compared with `hmac.compare_digest`, so the check is not timing-attackable.
- The workspace folder is local to your machine and gitignored by default.

```bash
# local only — no token needed
python server/agora_mcp.py --workspace ~/.agora/main

# exposed — token required, and enforced
AGORA_TOKEN=$(openssl rand -hex 32) \
  python server/agora_mcp.py --http --host 0.0.0.0 --port 8848 --workspace ~/.agora/main
```

> [!WARNING]
> Put HTTPS in front of any non-loopback deployment. The bearer token protects
> authorisation, not confidentiality in transit.

---

## Tests

The coordination engine is pure standard library, so the suite needs no dependencies and
no MCP client:

```bash
python -m unittest discover -s tests -v
```

28 tests covering lease expiry, lock contention, handoff lifecycle, message targeting,
event-log monotonicity, UTF-8 round-tripping — and genuine concurrency: eight threads race
for one task and the suite asserts that **exactly one wins**. CI runs all of it on Ubuntu, macOS and Windows
across Python 3.10 and 3.12, so the file-locking behaviour is proven on NTFS, APFS and
ext4 rather than mocked.

---

## Repository layout

```
server/           canonical MCP server + coordination engine
  agora_mcp.py      19 MCP tools; thin wrapper, no business logic
  store.py          all coordination state (stdlib only)
  bridge.py         serves the live dashboard
plugin/           self-contained Claude Code plugin (CI enforces it matches server/)
dashboard/        live web dashboard for watching the room
docs/             the documentation site published to GitHub Pages
tests/            store test suite
wire-local.*      configure local surfaces automatically
```

`plugin/server/` is a deliberate copy so the plugin bundles standalone. A CI job diffs it
against `server/` on every push and fails the build the moment the two drift.

---

## Known limitations

Stated plainly, because coordination software that oversells its guarantees is worse than
useless:

- **Presence assumes o