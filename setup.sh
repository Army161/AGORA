#!/usr/bin/env bash
# Agora one-time setup — run this on your machine, not in a shared env.
# Sets AGORA_WORKSPACE and AGORA_TOKEN, installs deps, starts the bridge.
set -e

# ── 1. Workspace path ────────────────────────────────────────────────────────
AGORA_WORKSPACE="${AGORA_WORKSPACE:-$HOME/.agora/main}"
echo "Workspace : $AGORA_WORKSPACE"
mkdir -p "$AGORA_WORKSPACE"

# ── 2. Secret token ──────────────────────────────────────────────────────────
if [ -z "$AGORA_TOKEN" ]; then
  AGORA_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  echo ""
  echo "Generated token — add this to your shell profile and keep it secret:"
  echo "  export AGORA_TOKEN=\"$AGORA_TOKEN\""
  echo ""
fi
export AGORA_WORKSPACE AGORA_TOKEN

# ── 3. Dependencies ──────────────────────────────────────────────────────────
pip install -q -r "$(dirname "$0")/server/requirements.txt"

# ── 4. Smoke-test the bridge ─────────────────────────────────────────────────
echo "Starting bridge on http://localhost:8849 …"
python3 "$(dirname "$0")/server/bridge.py" \
  --workspace "$AGORA_WORKSPACE" \
  --port 8849 \
  --seed \
  "$@"
