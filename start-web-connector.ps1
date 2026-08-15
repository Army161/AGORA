<#
  start-web-connector.ps1 — run the Agora MCP server with real OAuth 2.1 (Dynamic
  Client Registration + PKCE) so claude.ai web, Claude Design, and Claude Chrome can
  attach as a Custom Connector. Those surfaces don't accept a pasted bearer token —
  they discover OAuth metadata, self-register a client, then send your browser
  through a normal authorization flow. This is the server side of that handshake.

  ORDER MATTERS — the tunnel must be running FIRST, because the server has to
  advertise its real public URL in its OAuth metadata from the moment it starts:

    1. Start the tunnel and copy the HTTPS URL it prints:
         cloudflared tunnel --url http://localhost:8848
         (or: ngrok http 8848)
    2. Run this script WITH that URL:
         .\start-web-connector.ps1 -PublicUrl "https://your-tunnel-url.trycloudflare.com"
    3. In the surface: Settings -> Connectors -> Add Custom Connector ->
         URL: https://your-tunnel-url.trycloudflare.com/mcp
       It self-registers automatically. Your browser is sent to a consent page —
       type the passphrase this script prints (or your own -Token) once to approve.

  Usage (PowerShell, from inside the AGORA repo):
    .\start-web-connector.ps1 -PublicUrl "https://xxxx.trycloudflare.com"
    .\start-web-connector.ps1 -PublicUrl "https://xxxx.trycloudflare.com" -Token "mypassphrase"
#>
param(
  [Parameter(Mandatory=$true)]
  [string]$PublicUrl,
  [string]$Workspace = "$HOME\.agora\main",
  [int]$Port = 8848,
  [string]$Token = ""
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
$PublicUrl = $PublicUrl.TrimEnd('/')

# ── Pick a Python that actually has the HTTP+OAuth deps (same probe as wire-local.ps1) ──
$candidates = Get-Command py, python, python3 -ErrorAction SilentlyContinue |
              Select-Object -ExpandProperty Source -Unique
if (-not $candidates) { Write-Error "Python not found on PATH."; exit 1 }
$PY = $null
foreach ($cand in $candidates) {
  & $cand -c "import mcp.server.auth.provider, pydantic, uvicorn, starlette" 2>$null
  if ($LASTEXITCODE -eq 0) { $PY = $cand; break }
}
if (-not $PY) {
  $PY = $candidates | Select-Object -First 1
  $req = Join-Path $RepoDir "server\requirements.txt"
  Write-Warning "No Python on PATH can import the HTTP+OAuth deps (mcp + pydantic + uvicorn + starlette)."
  Write-Warning "Install them:  & `"$PY`" -m pip install -r `"$req`""
}

# ── Ensure an approval passphrase (typed once per connector at the consent screen) ──
if (-not $Token) {
  if ($env:AGORA_TOKEN) {
    $Token = $env:AGORA_TOKEN
  } else {
    $Token = & $PY -c "import secrets; print(secrets.token_urlsafe(24))"
    Write-Host ""
    Write-Host "Generated an approval passphrase (save it — you'll type it once per connector," -ForegroundColor Yellow
    Write-Host "at the consent screen):" -ForegroundColor Yellow
    Write-Host "    $Token" -ForegroundColor Yellow
  }
}

Write-Host ""
Write-Host "Starting Agora MCP HTTP server with OAuth ..."
Write-Host "  Workspace  : $WS"
Write-Host "  Public URL : $PublicUrl"
Write-Host "  Port       : $Port  (loopback; the tunnel handles the public side)"
Write-Host ""
Write-Host "Custom connector URL for claude.ai / Design / Chrome:"
Write-Host "    $PublicUrl/mcp" -ForegroundColor Cyan
Write-Host ""
Write-Host "Add it: Settings -> Connectors -> Add Custom Connector -> paste that URL."
Write-Host "It self-registers automatically; your browser opens a consent page — type"
Write-Host "the passphrase above there once to approve."
Write-Host ""

& $PY $Server --http --oauth --public-url $PublicUrl --host 127.0.0.1 --port $Port --workspace $WS --token $Token
