<#
  start-web-connector.ps1 — run the Agora MCP server over HTTP so remote surfaces
  (claude.ai web, Claude Design, Claude Chrome) can attach via a Custom Connector.

  Usage (PowerShell, from inside the AGORA repo):
    .\start-web-connector.ps1
    .\start-web-connector.ps1 -Workspace "$HOME\.agora\main" -Port 8848

  Binds to 127.0.0.1 only. You then expose it over HTTPS with a tunnel:
    cloudflared tunnel --url http://localhost:8848      (no account needed)
    ngrok http 8848

  A bearer token is REQUIRED here because the tunnel makes the room reachable
  from the internet. If AGORA_TOKEN isn't set, this script generates one and
  prints it — paste it into the connector's auth when you add it.
#>
param(
  [string]$Workspace = "$HOME\.agora\main",
  [int]$Port = 8848
)
$ErrorActionPreference = "Stop"

$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Server  = Join-Path $RepoDir "server\agora_mcp.py"
if (-not (Test-Path -LiteralPath $Server)) {
  Write-Error "server\agora_mcp.py not found next to this script — run it from inside the AGORA repo."
  exit 1
}

New-Item -ItemType Directory -Force -Path $Workspace | Out-Null
$WS = (Resolve-Path -LiteralPath $Workspace).Path

# ── Pick a Python that actually has the deps (same probe as wire-local.ps1) ────
$candidates = Get-Command py, python, python3 -ErrorAction SilentlyContinue |
              Select-Object -ExpandProperty Source -Unique
if (-not $candidates) { Write-Error "Python not found on PATH."; exit 1 }
$PY = $null
foreach ($cand in $candidates) {
  & $cand -c "import mcp, pydantic, uvicorn, starlette" 2>$null
  if ($LASTEXITCODE -eq 0) { $PY = $cand; break }
}
if (-not $PY) {
  $PY = $candidates | Select-Object -First 1
  $req = Join-Path $RepoDir "server\requirements.txt"
  Write-Warning "No Python on PATH can import the HTTP deps (mcp + pydantic + uvicorn + starlette)."
  Write-Warning "Install them:  & `"$PY`" -m pip install -r `"$req`""
}

# ── Ensure a bearer token (the tunnel makes this public) ──────────────────────
if (-not $env:AGORA_TOKEN) {
  $env:AGORA_TOKEN = & $PY -c "import secrets; print(secrets.token_urlsafe(32))"
  Write-Host ""
  Write-Host "Generated a new AGORA_TOKEN (save it — you'll paste it into the connector):" -ForegroundColor Yellow
  Write-Host "    $env:AGORA_TOKEN" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Starting Agora MCP HTTP server …"
Write-Host "  Workspace : $WS"
Write-Host "  Bind      : 127.0.0.1:$Port  (loopback; the tunnel handles the public side)"
Write-Host "  Auth      : bearer token (set)"
Write-Host ""
Write-Host "In a SECOND terminal, expose it over HTTPS:"
Write-Host "    cloudflared tunnel --url http://localhost:$Port"
Write-Host "  (or)  ngrok http $Port"
Write-Host ""
Write-Host "Then add a Custom Connector in the surface (web / Design / Chrome):"
Write-Host "    URL    : the https://...trycloudflare.com (or ngrok) URL  +  /mcp  if asked for a path"
Write-Host "    Token  : the AGORA_TOKEN above (as the bearer token / Authorization header)"
Write-Host ""

& $PY $Server --http --host 127.0.0.1 --port $Port --workspace $WS
