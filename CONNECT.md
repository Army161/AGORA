# Connecting the 5 surfaces to one Agora room (local hub)

## Fastest path: one command for the two local surfaces
Prereqs on the machine: Python installed (python.org — on Windows tick "Add to PATH"),
plus Claude Desktop and/or Claude Code. From inside this repo:

**Windows (PowerShell — native, no bash needed):**
```powershell
powershell -ExecutionPolicy Bypass -File .\wire-local.ps1
# or name a room:  ... -File .\wire-local.ps1 -Workspace "$HOME\.agora\landing"
# preview only:    ... -File .\wire-local.ps1 -Print
```

**macOS / Linux (or Windows Git Bash / WSL):**
```bash
bash wire-local.sh                 # uses ~/.agora/main
# or: bash wire-local.sh ~/.agora/landing-redesign   # name your own room
# preview only: bash wire-local.sh --print
```

Either one resolves ONE literal absolute path, writes that identical string into both the
Claude Desktop config and Claude Code (`claude mcp add`), backs up anything it touches,
and verifies both surfaces resolve to the same room. Then restart Desktop, run
`/agora-board` in Code, and do the "Verify the room" steps below. The rest of this file is
the manual/per-surface guide.

## The one golden rule
Every surface must point at the **same workspace folder**. The shipped default is
`~/.agora/main` (call it `$WS` below) — use it as-is and every surface lands in the same
room with zero editing. The engine is cross-process safe: several surfaces can run their
own server against the same folder at once; the mutex + atomic writes keep it clean.

Why `~` is safe here (but `$HOME`/`$VAR` are not): the Agora server itself runs
`os.path.expanduser` on the workspace arg, so `~/.agora/main` resolves to the *same*
absolute path for your user on your machine no matter which surface launched it. A JSON
config consumer, by contrast, will **not** expand `$HOME` or `${VAR}` — those reach the
server as literal strings and land you in a different (broken) room. So: `~/.agora/main`
or a literal absolute path — never `$HOME`/`$VAR` — and `wire-local.sh` writes a fully
literal path if you'd rather not rely on `~` at all.

One-time on the machine that holds the folder:
```bash
pip install -r server/requirements.txt
export WS=~/.agora/main           # the default room — or pick your own
```

## 1. Claude Code  (easiest — zero edits)
Use the plugin (auto-launches the server). `plugin/.mcp.json` ships ready to run: the
server path resolves via `${CLAUDE_PLUGIN_ROOT}` and the workspace defaults to the shared
`~/.agora/main` room — no editing needed. Only touch it to pick a *different* room: change
`env.AGORA_WORKSPACE` to another `~/.agora/<name>` or a literal absolute path.
Verify: run `/agora-board`.

## 2. Claude Desktop / Cowork
Add Agora to the desktop app's MCP config (a JSON with an `mcpServers` block). Copy the
`agora` block from `desktop-mcp-config.json` and edit the **one** machine-specific value —
the absolute path to `agora_mcp.py` in this repo (the `~/.agora/main` workspace stays
as-is):
```json
{"mcpServers":{"agora":{"command":"python3",
 "args":["/ABSOLUTE/.../AGORA/server/agora_mcp.py","--workspace","~/.agora/main","--name","Agora"]}}}
```
Or skip the editing entirely: run `wire-local.sh` / `wire-local.ps1`, which fills that
path in for you. Confirm the exact config-file location for your build at
https://support.claude.com or https://docs.claude.com, then restart the app. Verify by
asking it to call `agora_board`.

## 3. Design, 4. Chrome extension, and 5. claude.ai web  (need a public HTTPS connector)
These three attach the same way: as a **Custom Connector** over HTTPS. They do NOT accept a
pasted bearer token — a Custom Connector discovers OAuth metadata and self-registers a
client (RFC 7591 Dynamic Client Registration), then sends your browser through a normal
OAuth authorization-code + PKCE flow. `agora_mcp.py --oauth` implements that handshake for
real: any client may register, but nobody gets a token without your passphrase at a consent
page only you can approve.

Order matters — start the tunnel first, since the server has to advertise its real public
URL in its OAuth metadata from the moment it starts:
```bash
cloudflared tunnel --url http://localhost:8848      # copy the https://...trycloudflare.com URL
export AGORA_PUBLIC_URL=https://your-tunnel-url.trycloudflare.com
export AGORA_WORKSPACE="$WS"
./start-web-connector.sh                             # or start-web-connector.ps1 -PublicUrl ... on Windows
```
It prints an approval passphrase (or reuses `$AGORA_TOKEN` if you set one). Then in each
surface: **Settings → Connectors → Add Custom Connector** → paste `$AGORA_PUBLIC_URL/mcp`.
It self-registers automatically; your browser opens a consent page — type the passphrase
once per connector to approve. After that, each surface calls `agora_join` with its own
`surface` value (`design`, `chrome`, or `claude_ai`) exactly like Code/Desktop do.

## Verify the room (any two surfaces)
1. A: `agora_join` → `agora_add_task` → `agora_claim_task`.
2. B: `agora_join` → `agora_board` (sees A + the task) → claim the same task → should be
   refused → `agora_create_handoff` to A.
3. A: `agora_list_handoffs` → `agora_ack_handoff` → `agora_complete_handoff`.
4. Open `$WS/board.md`, `$WS/updates/UPDATES.md`, `$WS/handoffs/` — all should reflect it.
