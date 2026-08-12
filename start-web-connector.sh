#!/usr/bin/env bash
# Start the MCP server in HTTP mode with real OAuth 2.1 (Dynamic Client Registration
# + PKCE) so claude.ai web, Claude Design, and Claude Chrome can attach as a Custom
# Connector. These surfaces don't accept a pasted bearer token — they discover OAuth
# metadata and self-register a client, then send your browser through a normal
# authorization flow. This script's server implements that for real.
#
# ORDER MATTERS: the tunnel must be running FIRST, because the server has to
# advertise its real public URL in its OAuth metadata from the moment it starts.
#
#   1. Start the tunnel and copy the HTTPS URL it prints:
#        cloudflared tunnel --url http://localhost:8848
#        (or: ngrok http 8848)
#   2. export AGORA_PUBLIC_URL=https://your-tunnel-url.trycloudflare.com
#   3. export AGORA_WORKSPACE=$HOME/.agora/main
#   4. Run this script.
#   5. In the surface: Settings → Connectors → Add Custom Connector →
#        URL: $AGORA_PUBLIC_URL/mcp
#      It self-registers automatically. Your browser is sent to a consent page —
#      type the passphrase this script prints (or your AGORA_TOKEN) once to approve.
set -e

: "${AGORA_WORKSPACE:?'Set AGORA_WORKSPACE first, e.g. export AGORA_WORKSPACE=$HOME/.agora/main'}"
: "${AGORA_PUBLIC_URL:?'Set AGORA_PUBLIC_URL first — start the tunnel, copy its https URL, then: export AGORA_PUBLIC_URL=https://your-tunnel-url'}"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -z "${AGORA_TOKEN:-}" ]; then
  export AGORA_TOKEN="$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")"
  echo ""
  echo "Generated an approval passphrase (save it — you'll type it once per connector"
  echo "at the consent screen):"
  echo "    $AGORA_TOKEN"
fi

echo ""
echo "Starting Agora MCP HTTP server with OAuth …"
echo "  Workspace  : $AGORA_WORKSPACE"
echo "  Public URL : $AGORA_PUBLIC_URL"
echo "  Port       : 8848 (loopback; the tunnel handles the public side)"
echo ""
echo "Custom connector URL: $AGORA_PUBLIC_URL/mcp"
echo ""

python3 "$REPO_DIR/server/agora_mcp.py" \
  --http \
  --oauth \
  --public-url "$AGORA_PUBLIC_URL" \
  --host 127.0.0.1 \
  --port 8848 \
  --workspace "$AGORA_WORKSPACE"
