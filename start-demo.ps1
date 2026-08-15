<#
  start-demo.ps1 — bring the whole web-connector stack up in one command, and
  refuse to claim it is ready until the OAuth chain actually verifies.

  Two tunnel backends:

    -Tunnel tailscale   (default) Tailscale Funnel. STABLE hostname that survives
                        restarts, so a Custom Connector added once keeps working.
                        Requires `tailscale up` to have been run, plus HTTPS
                        certs and the Funnel attribute enabled for the tailnet.

    -Tunnel cloudflared cloudflared quick tunnel. No account, no domain, but a
                        NEW random hostname every run — every surface must then
                        re-add the connector, not merely re-consent.

  Usage:
    .\start-demo.ps1                          # Tailscale Funnel (stable)
    .\start-demo.ps1 -Tunnel cloudflared      # throwaway URL
    .\start-demo.ps1 -Token "my-passphrase"   # reuse a known passphrase
    .\start-demo.ps1 -Stop                    # tear everything down
#>
param(
  [ValidateSet('tailscale','cloudflared')]
  [string]$Tunnel = 'tailscale',
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
$TS        = "$env:ProgramFiles\Tailscale\tailscale.exe"

function Info($t) { Write-Host $t -ForegroundColor Cyan }
function Ok($t)   { Write-Host "  OK   $t" -ForegroundColor Green }
function Bad($t)  { Write-Host "  FAIL $t" -ForegroundColor Red }
function Hint($t) { Write-Host "       $t" -ForegroundColor Yellow }

# ---------------------------------------------------------------- teardown --
function Stop-Stack {
  if (Test-Path $StateFile) {
    try {
      $s = Get-Content $StateFile -Raw | ConvertFrom-Json
      foreach ($procId in @($s.tunnelPid, $s.serverPid)) {
        if ($procId) { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue }
      }
    } catch { }
    Remove-Item $StateFile -Force -ErrorAction SilentlyContinue
  }
  # Fall back to whatever holds the port, so a stale run from a previous session
  # cannot leave a zombie listening and silently serving an old workspace.
  $held = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  foreach ($c in $held) { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue }
  Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  # Funnel is a persistent serve-config on the tailnet, not a process — turning
  # it off matters, or the hostname keeps answering after the server is gone.
  if (Test-Path $TS) { & $TS funnel --https=443 off 2>$null | Out-Null }
}

if ($Stop) {
  Info "Stopping Agora demo stack ..."
  Stop-Stack
  Ok "stopped"
  exit 0
}

# ------------------------------------------------------------ prerequisites --
Info "Checking prerequisites ..."
if (-not (Test-Path -LiteralPath $Server))   { Bad "server\agora_mcp.py not found - run from inside the AGORA repo."; exit 1 }
if (-not (Test-Path -LiteralPath $Verifier)) { Bad "verify-connector.ps1 not found next to this script."; exit 1 }

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
  Hint "Install them:  python -m pip install -r server\requirements.txt"
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
# URL into the OAuth metadata at boot and cannot learn the hostname later.
$PublicUrl  = $null
$tunnelProc = $null

if ($Tunnel -eq 'tailscale') {
  Info "Using Tailscale Funnel (stable hostname) ..."
  if (-not (Test-Path $TS)) {
    Bad "tailscale.exe not found at $TS"
    Hint "Install it:  winget install --id Tailscale.Tailscale --exact"
    exit 1
  }

  $statusJson = & $TS status --json 2>$null | Out-String
  if (-not $statusJson.Trim()) { Bad "could not read tailscale status."; exit 1 }
  try { $status = $statusJson | ConvertFrom-Json } catch { Bad "tailscale status was not valid JSON."; exit 1 }

  if ($status.BackendState -ne "Running") {
    Bad "Tailscale is not logged in (BackendState=$($status.BackendState))."
    Hint "Run:  & '$TS' up"
    Hint "then follow the login URL it prints, and re-run this script."
    exit 1
  }

  # DNSName arrives fully qualified with a trailing dot; strip it for a URL.
  $dns = $status.Self.DNSName
  if (-not $dns) { Bad "tailscale reported no DNSName for this machine."; exit 1 }
  $dns = $dns.TrimEnd('.')
  $PublicUrl = "https://$dns"
  Ok "tailnet hostname: $dns"

  Info "Enabling Funnel on port $Port ..."
  $funnelOut = & $TS funnel --bg $Port 2>&1 | Out-String
  if ($LASTEXITCODE -ne 0) {
    Bad "could not enable Funnel."
    foreach ($line in ($funnelOut -split "`n" | Where-Object { $_.Trim() })) { Hint $line.Trim() }
    Hint "Funnel needs HTTPS certificates and the 'funnel' node attribute enabled"
    Hint "for your tailnet. The output above usually contains a link that does both."
    exit 1
  }
  Ok "funnel active -> $PublicUrl"

} else {
  Info "Using cloudflared quick tunnel (throwaway hostname) ..."
  if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) { Bad "cloudflared not on PATH."; exit 1 }
  Remove-Item $TunnelLog, "$TunnelLog.out" -Force -ErrorAction SilentlyContinue
  $tunnelProc = Start-Process -FilePath "cloudflared" `
                  -ArgumentList 'tunnel','--url',"http://localhost:$Port" `
                  -RedirectStandardError $TunnelLog `
                  -RedirectStandardOutput "$TunnelLog.out" `
                  -WindowStyle Hidden -PassThru
  for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 750
    if (Test-Path $TunnelLog) {
      $m = (Select-String -Path $TunnelLog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -AllMatches -ErrorAction SilentlyContinue).Matches
      if ($m -and $m.Count -gt 0) { $PublicUrl = ($m.Value | Select-Object -Unique -First 1); break }
    }
  }
  if (-not $PublicUrl) {
    Bad "tunnel did not report a public URL within 30s. Last lines:"
    Get-Content $TunnelLog -Tail 12 -ErrorAction SilentlyContinue | ForEach-Object { Hint $_ }
    Stop-Stack; exit 1
  }
  Ok "tunnel: $PublicUrl"
}

# ---------------------------------------------------------------- passphrase --
if (-not $Token) {
  $Token = if ($env:AGORA_TOKEN) { $env:AGORA_TOKEN } else { & $PY -c "import secrets; print(secrets.token_urlsafe(24))" }
}

# -------------------------------------------------------------------- server --
Info "Starting Agora MCP server (loopback; the tunnel fronts it) ..."
Remove-Item $ServerLog, "$ServerLog.err" -Force -ErrorAction SilentlyContinue
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
  Get-Content "$ServerLog.err" -Tail 15 -ErrorAction SilentlyContinue | ForEach-Object { Hint $_ }
  Get-Content $ServerLog      -Tail 15 -ErrorAction SilentlyContinue | ForEach-Object { Hint $_ }
  Stop-Stack; exit 1
}
Ok "listening on 127.0.0.1:$Port"

@{ tunnelPid = $(if ($tunnelProc) { $tunnelProc.Id } else { $null })
   serverPid = $server.Id
   publicUrl = $PublicUrl
   backend   = $Tunnel } | ConvertTo-Json | Set-Content $StateFile

# -------------------------------------------------------------------- verify --
Write-Host ""
Info "Verifying the OAuth chain end to end ..."
& $Verifier -PublicUrl $PublicUrl
$verifyExit = $LASTEXITCODE

Write-Host ""
if ($verifyExit -ne 0) {
  Bad "stack is up but did NOT verify - do not hand this URL out."
  Hint "Tear down with:  .\start-demo.ps1 -Stop"
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
if ($Tunnel -eq 'tailscale') {
  Write-Host "This hostname is stable across restarts, so the connector only has to be" -ForegroundColor DarkGray
  Write-Host "added once. OAuth registrations are still in memory, so a server restart" -ForegroundColor DarkGray
  Write-Host "means each surface re-consents - it does not mean re-adding the connector." -ForegroundColor DarkGray
} else {
  Write-Host "This hostname is THROWAWAY. Restarting means every surface must re-add" -ForegroundColor DarkGray
  Write-Host "the connector, not just re-consent. Leave it running for the demo." -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "Tear down with:  .\start-demo.ps1 -Stop" -ForegroundColor DarkGray
exit 0
