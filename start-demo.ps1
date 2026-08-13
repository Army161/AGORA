<#
  start-demo.ps1 — bring the whole web-connector stack up in one command, and
  refuse to claim it is ready until the OAuth chain actually verifies.

  It starts a cloudflared quick tunnel, reads the public URL it prints, boots the
  Agora MCP server bound to loopback with OAuth advertising that exact URL, then
  runs verify-connector.ps1 against it. If any step fails it says which one.

  Quick tunnels get a NEW random hostname every run. That is the trade for
  needing no account and no domain. This script makes re-establishing the stack
  a ~20 second operation instead of a manual four-step dance.

  Usage:
    .\start-demo.ps1
    .\start-demo.ps1 -Token "my-passphrase"     # reuse a passphrase you know
    .\start-demo.ps1 -Stop                      # tear everything down

  Requires: cloudflared on PATH, and a Python that can import the OAuth deps
  (mcp.server.auth, pydantic, uvicorn, starlette).
#>
param(
  [string]$Workspace = "$HOME\.agora\main",
  [int]$Port = 8848,
  [string]$Token = "",
  [switch]$Stop
)

$ErrorActionPreference = "Stop"
$RepoDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$Server    = Join-Path $RepoDir "server\agora_mcp.py"
$Verifier  = Join-Path $RepoDir "verify-connector.ps1"
$StateFile = Join-Path $env:TEMP "agora-demo-state.json"
$TunnelLog = Join-Path $env:TEMP "agora-cf.log"
$ServerLog = Join-Path $env:TEMP "agora-server.log"

function Info($t) { Write-Host $t -ForegroundColor Cyan }
function Ok($t)   { Write-Host "  OK   $t" -ForegroundColor Green }
function Bad($t)  { Write-Host "  FAIL $t" -ForegroundColor Red }

# ---------------------------------------------------------------- teardown --
function Stop-Stack {
  # Kill by recorded PID where possible; fall back to whatever holds the port,
  # so a stale run from a previous session cannot leave a zombie listening.
  if (Test-Path $StateFile) {
    try {
      $s = Get-Content $StateFile -Raw | ConvertFrom-Json
      foreach ($procId in @($s.tunnelPid, $s.serverPid)) {
        if ($procId) { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue }
      }
    } catch { }
    Remove-Item $StateFile -Force -ErrorAction SilentlyContinue
  }
  $held = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  foreach ($c in $held) { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue }
  Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

if ($Stop) {
  Info "Stopping Agora demo stack ..."
  Stop-Stack
  Ok "stopped"
  exit 0
}

# ------------------------------------------------------------ prerequisites --
Info "Checking prerequisites ..."
if (-not (Test-Path -LiteralPath $Server)) { Bad "server\agora_mcp.py not found - run from inside the AGORA repo."; exit 1 }
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) { Bad "cloudflared not on PATH."; exit 1 }
Ok "cloudflared present"

# Pick an interpreter that can actually import the OAuth stack. A machine with
# several Pythons will happily run the wrong one and fail deep inside startup.
$candidates = Get-Command py, python, python3 -ErrorAction SilentlyContinue |
              Select-Object -ExpandProperty Source -Unique
$PY = $null
foreach ($cand in $candidates) {
  & $cand -c "import mcp.server.auth.provider, pydantic, uvicorn, starlette" 2>$null
  if ($LASTEXITCODE -eq 0) { $PY = $cand; break }
}
if (-not $PY) {
  Bad "no Python on PATH can import the OAuth deps (mcp + pydantic + uvicorn + starlette)."
  Write-Host "       Install them:  python -m pip install -r server\requirements.txt" -ForegroundColor Yellow
  exit 1
}
Ok "python: $PY"

New-Item -ItemType Directory -Force -Path $Workspace | Out-Null
$WS = (Resolve-Path -LiteralPath $Workspace).Path
Ok "workspace: $WS"

Info "Clearing any previous run ..."
Stop-Stack
Start-Sleep -Seconds 1
Ok "clear"

# ------------------------------------------------------------------ tunnel --
# The tunnel must exist BEFORE the server starts: the server bakes its public
# URL into the OAuth metadata at boot, so it cannot learn the hostname later.
Info "Starting cloudflared tunnel ..."
Remove-Item $TunnelLog -Force -ErrorAction SilentlyContinue
$tunnel = Start-Process -FilePath "cloudflared" `
            -ArgumentList 'tunnel','--url',"http://localhost:$Port" `
            -RedirectStandardError $TunnelLog `
            -RedirectStandardOutput "$TunnelLog.out" `
            -WindowStyle Hidden -PassThru

$PublicUrl = $null
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Milliseconds 750
  if (Test-Path $TunnelLog) {
    $m = (Select-String -Path $TunnelLog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -AllMatches -ErrorAction SilentlyContinue).Matches
    if ($m -and $m.Count -gt 0) { $PublicUrl = ($m.Value | Select-Object -Unique -First 1); break }
  }
}
if (-not $PublicUrl) {
  Bad "tunnel did not report a public URL within 30s. Last lines:"
  Get-Content $TunnelLog -Tail 12 -ErrorAction SilentlyContinue | ForEach-Object { "       $_" }
  Stop-Stack
  exit 1
}
Ok "tunnel: $PublicUrl"

# ---------------------------------------------------------------- passphrase --
if (-not $Token) {
  $Token = if ($env:AGORA_TOKEN) { $env:AGORA_TOKEN } else { & $PY -c "import secrets; print(secrets.token_urlsafe(24))" }
}

# -------------------------------------------------------------------- server --
Info "Starting Agora MCP server (loopback; the tunnel fronts it) ..."
Remove-Item $ServerLog -Force -ErrorAction SilentlyContinue
$server = Start-Process -FilePath $PY `
            -ArgumentList $Server,'--http','--oauth','--public-url',$PublicUrl,
                          '--host','127.0.0.1','--port',"$Port",'--workspace',$WS,'--token',$Token `
            -WorkingDirectory $RepoDir `
            -RedirectStandardOutput $ServerLog `
            -RedirectStandardError "$ServerLog.err" `
            -WindowStyle Hidden -PassThru

$listening = $false
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Milliseconds 700
  if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { $listening = $true; break }
  if ($server.HasExited) { break }
}
if (-not $listening) {
  Bad "server never started listening on $Port. Last lines:"
  Get-Content "$ServerLog.err" -Tail 15 -ErrorAction SilentlyContinue | ForEach-Object { "       $_" }
  Get-Content $ServerLog     -Tail 15 -ErrorAction SilentlyContinue | ForEach-Object { "       $_" }
  Stop-Stack
  exit 1
}
Ok "listening on 127.0.0.1:$Port"

@{ tunnelPid = $tunnel.Id; serverPid = $server.Id; publicUrl = $PublicUrl } |
  ConvertTo-Json | Set-Content $StateFile

# -------------------------------------------------------------------- verify --
Write-Host ""
Info "Verifying the OAuth chain end to end ..."
& $Verifier -PublicUrl $PublicUrl
$verifyExit = $LASTEXITCODE

Write-Host ""
if ($verifyExit -ne 0) {
  Bad "stack is up but did NOT verify - do not hand this URL out."
  Write-Host "Tear down with:  .\start-demo.ps1 -Stop" -ForegroundColor Yellow
  exit 1
}

Write-Host "=================== READY ===================" -ForegroundColor Green
Write-Host "Custom Connector URL:" -ForegroundColor White
Write-Host "    $PublicUrl/mcp" -ForegroundColor Cyan
Write-Host ""
Write-Host "Consent passphrase (type once per surface):" -ForegroundColor White
Write-Host "    $Token" -ForegroundColor Yellow
Write-Host ""
Write-Host "Add it in each surface: Settings -> Connectors -> Add Custom Connector."
Write-Host ""
Write-Host "Note: OAuth registrations live in memory, so restarting the server" -ForegroundColor DarkGray
Write-Host "forces every surface to re-consent. Start this once and leave it up." -ForegroundColor DarkGray
Write-Host ""
Write-Host "Tear down with:  .\start-demo.ps1 -Stop" -ForegroundColor DarkGray
exit 0
