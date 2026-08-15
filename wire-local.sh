#!/usr/bin/env bash
# wire-local.sh — wire Claude Code + Claude Desktop/Cowork to ONE Agora room.
#
# Run this ON YOUR machine (the one with Claude Desktop / Claude Code installed).
# It resolves a SINGLE literal absolute workspace path and writes that identical
# string into both surfaces, then verifies they match — so you can never end up
# with two surfaces sitting in separate rooms.
#
#   bash wire-local.sh                       # uses ~/.agora/main
#   bash wire-local.sh ~/.agora/landing      # custom room
#   bash wire-local.sh --print               # show the config blocks, change nothing
#   bash wire-local.sh --dry-run ~/.agora/x  # say what it would do, change nothing
#
# Local stdio wiring needs no token (it never leaves your machine). The token is
# only for the HTTPS/web path — see start-web-connector.sh for that phase.
set -euo pipefail

MODE="write"
WS_INPUT=""
for arg in "$@"; do
  case "$arg" in
    --print)   MODE="print" ;;
    --dry-run) MODE="dryrun" ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)         WS_INPUT="$arg" ;;
  esac
done
WS_INPUT="${WS_INPUT:-$HOME/.agora/main}"

# ── Resolve ONE literal absolute path (no ~, no $VAR — the actual string) ──────
mkdir -p "$WS_INPUT"
WS="$(cd "$WS_INPUT" && pwd -P)"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SERVER="$REPO_DIR/server/agora_mcp.py"
[ -f "$SERVER" ] || { echo "ERROR: $SERVER not found — run this from inside the AGORA repo." >&2; exit 1; }

# On Git Bash / MSYS / Cygwin, `pwd -P` yields POSIX paths (/c/...) that native
# Windows Python and Claude Desktop can't resolve. Convert to Windows-native form.
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    if command -v cygpath >/dev/null 2>&1; then
      WS="$(cygpath -w "$WS")"
      SERVER="$(cygpath -w "$SERVER")"
    else
      echo "WARNING: on a Windows shell but 'cygpath' not found — the written paths" >&2
      echo "         may be POSIX-style (/c/...) and unusable by native Windows apps." >&2
    fi
    ;;
esac

# ── Pick a Python that actually has the Agora deps (mcp + pydantic) ───────────
# Probe each candidate rather than taking the first on PATH: the interpreter that
# launches first isn't always the one where `pip install -r requirements.txt` ran,
# and an app spawning a dep-less Python just sees the MCP server "fail to connect".
PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import mcp, pydantic" >/dev/null 2>&1; then
    PY="$cand"; break
  fi
done
if [ -z "$PY" ]; then
  if command -v python3 >/dev/null 2>&1; then PY="python3"
  elif command -v python >/dev/null 2>&1; then PY="python"
  else echo "ERROR: neither python3 nor python found on PATH." >&2; exit 1; fi
  echo "WARNING: '$PY' cannot import the Agora deps (mcp + pydantic)." >&2
  echo "         Install them first:  $PY -m pip install -r \"$REPO_DIR/server/requirements.txt\"" >&2
  echo "         The server will fail to start until you do." >&2
fi

# ── Locate the Claude Desktop config for this OS ──────────────────────────────
case "$(uname -s)" in
  Darwin) DESKTOP_CFG="$HOME/Library/Application Support/Claude/claude_desktop_config.json" ;;
  Linux)  DESKTOP_CFG="$HOME/.config/Claude/claude_desktop_config.json" ;;
  MINGW*|MSYS*|CYGWIN*) DESKTOP_CFG="${APPDATA:-$HOME/AppData/Roaming}/Claude/claude_desktop_config.json" ;;
  *)      DESKTOP_CFG="$HOME/.config/Claude/claude_desktop_config.json" ;;
esac

echo "──────────────────────────────────────────────────────────────"
echo "Agora room (one literal path used everywhere):"
echo "    $WS"
echo "Server:  $SERVER"
echo "Python:  $PY"
echo "Desktop config: $DESKTOP_CFG"
echo "──────────────────────────────────────────────────────────────"

# ── Show the exact blocks (always) ────────────────────────────────────────────
echo ""
echo "Claude Desktop  →  mcpServers.agora:"
cat <<JSON
    "agora": {
      "command": "$PY",
      "args": ["$SERVER", "--workspace", "$WS", "--name", "Agora"]
    }
JSON
echo ""
echo "Claude Code  →  equivalent registration:"
echo "    claude mcp add agora -s user -- $PY \"$SERVER\" --workspace \"$WS\" --name Agora"
echo ""

if [ "$MODE" = "print" ] || [ "$MODE" = "dryrun" ]; then
  echo "(${MODE}: no files changed.)"
  exit 0
fi

# ── 1. Merge into Claude Desktop config (back up first, idempotent) ────────────
mkdir -p "$(dirname "$DESKTOP_CFG")"
if [ -f "$DESKTOP_CFG" ]; then
  BAK="$DESKTOP_CFG.bak.$(date +%Y%m%d-%H%M%S)"
  cp "$DESKTOP_CFG" "$BAK"
  echo "Backed up existing Desktop config → $BAK"
  echo "  (restore anytime:  cp \"$BAK\" \"$DESKTOP_CFG\")"
fi

WS="$WS" SERVER="$SERVER" PY="$PY" CFG="$DESKTOP_CFG" "$PY" - <<'PYEOF'
import json, os
cfg, ws, server, py = os.environ["CFG"], os.environ["WS"], os.environ["SERVER"], os.environ["PY"]
data = {}
if os.path.exists(cfg):
    try:
        with open(cfg) as f:
            data = json.load(f) or {}
    except Exception as e:
        raise SystemExit(f"ERROR: existing {cfg} is not valid JSON ({e}). Fix or move it, then re-run.")
data.setdefault("mcpServers", {})["agora"] = {
    "command": py,
    "args": [server, "--workspace", ws, "--name", "Agora"],
}
with open(cfg, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print(f"Wrote agora → {cfg}")
PYEOF

# ── 2. Register with Claude Code (CLI if present, else print the command) ──────
if command -v claude >/dev/null 2>&1; then
  claude mcp remove agora -s user >/dev/null 2>&1 || true
  claude mcp add agora -s user -- "$PY" "$SERVER" --workspace "$WS" --name Agora
  echo "Registered agora with Claude Code (user scope)."
else
  echo "NOTE: 'claude' CLI not found — run this yourself in Claude Code:"
  echo "    claude mcp add agora -s user -- $PY \"$SERVER\" --workspace \"$WS\" --name Agora"
fi

# ── 3. Verify both surfaces carry the IDENTICAL literal path ───────────────────
echo ""
echo "Verifying both surfaces resolve to the same room…"
DESK_WS="$(WS="$WS" CFG="$DESKTOP_CFG" "$PY" - <<'PYEOF'
import json, os
d = json.load(open(os.environ["CFG"]))
args = d["mcpServers"]["agora"]["args"]
print(args[args.index("--workspace") + 1])
PYEOF
)"
if [ "$DESK_WS" = "$WS" ]; then
  echo "  ✓ Claude Desktop → $DESK_WS"
else
  echo "  ✗ Claude Desktop path mismatch: $DESK_WS  (expected $WS)" >&2; exit 1
fi
if command -v claude >/dev/null 2>&1 && claude mcp get agora >/dev/null 2>&1; then
  if claude mcp get agora 2>/dev/null | grep -qF -- "$WS"; then
    echo "  ✓ Claude Code → $WS"
  else
    echo "  ! Claude Code registered, but couldn't confirm the path string — check: claude mcp get agora" >&2
  fi
fi

echo ""
echo "Done. Next:"
echo "  1. Fully quit and reopen Claude Desktop (config is read at startup)."
echo "  2. In Claude Code, run /agora-board (or ask it to call agora_board)."
echo "  3. Prove the room: claim a task in one surface, try to claim it in the other"
echo "     (must be refused), then hand it off. See CONNECT.md → 'Verify the room'."
