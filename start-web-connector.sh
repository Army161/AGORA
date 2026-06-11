#!/usr/bin/env bash
# Start the MCP server in HTTP mode for the claude.ai web Custom Connector.
# Run AFTER setting AGORA_WORKSPACE and AGORA_TOKEN in your shell.
# Then expose port 8848 over HTTPS via cloudflared tunnel or ngrok.
set -e

: "${AGORA_WORKSPACE:?'Set AGORA_WORKSPACE first, e.g. export AGORA_WORKSPACE=$HOME/.agora/main'}"
: "${AGORA_TOKEN:?'Set AGORA_TOKEN first. Generate one: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\"'}"

REPO_DIR="$(dirname "$(realpath "$0")")"

echo "Starting Agora MCP HTTP server …"
echo "  Workspace : $AGORA_WORKSPACE"
echo "  Port      : 8848"
echo "  Auth      : bearer-token (set)"
echo ""
echo "Next steps after this starts:"
echo "  cloudflared: cloudflared tunnel --url http://localhost:8848"
echo "  ngrok:       ngrok http 8848"
echo ""
echo "Then in claude.ai → Settings → Connectors → Add Custom Connector:"
echo "  paste the HTTPS URL and your AGORA_TOKEN as the bearer token header."
echo ""

python3 "$REPO_DIR/server/agora_mcp.py" \
  --http \
  --host 127.0.0.1 \
  --port 8848 \
  --workspace "$AGORA_WORKSPACE"
