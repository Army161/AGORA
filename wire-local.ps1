<#
  wire-local.ps1 — wire Claude Code + Claude Desktop to ONE Agora room (Windows).

  Run in PowerShell, from inside the AGORA repo:
    powershell -ExecutionPolicy Bypass -File .\wire-local.ps1
    powershell -ExecutionPolicy Bypass -File .\wire-local.ps1 -Workspace "$HOME\.agora\landing"
    powershell -ExecutionPolicy Bypass -File .\wire-local.ps1 -Print     # show blocks, change nothing

  It resolves ONE literal absolute Windows path and writes that identical string
  into both Claude Desktop (config JSON) and Claude Code (claude mcp add), backs up
  anything it touches, and verifies both surfaces resolve to the same room.

  Local stdio wiring needs no token (it never leaves your machine). The token is
  only for the HTTPS/web path — see start-web-connector.sh for that phase.
#>
param(
  [string]$Workspace = "$HOME\.agora\main",
  [switch]$Print,
  [switch]$DryRun
)
$ErrorActionPreference = "Stop"

# ── Resolve ONE literal absolute path (no ~, no env vars in the JSON) ──────────
New-Item -ItemType Directory -Force -Path $Workspace | Out-Null
$WS = (Resolve-Path -LiteralPath $Workspace).Path

$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Server  = Join-Path $RepoDir "server\agora_mcp.py"
if (-not (Test-Path -LiteralPath $Server)) {
  Write-Error "server\agora_mcp.py not found next to this script — run it from inside the AGORA repo."
  exit 1
}

# ── Pick a Python that actually has the Agora deps (mcp + pydantic) ────────────
# Don't just take the first Python on PATH: the `py` launcher defaults to the
# NEWEST installed Python, which is often NOT the one where you ran
# `pip install -r server/requirements.txt`. Probe each candidate and pick the
# first that can import the server's dependencies — otherwise an app spawning it
# gets a ModuleNotFoundError and the MCP server silently "fails to connect".
$candidates = Get-Command py, python, python3 -ErrorAction SilentlyContinue |
              Select-Object -ExpandProperty Source -Unique
if (-not $candidates) {
  Write-Error "Python not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then re-run."
  exit 1
}
$PY = $null
foreach ($cand in $candidates) {
  & $cand -c "import mcp, pydantic" 2>$null
  if ($LASTEXITCODE -eq 0) { $PY = $cand; break }
}
if (-not $PY) {
  # None can import the deps — fall back to the first real Python but warn loudly,
  # since the server won't start until its requirements are installed there.
  $PY = $candidates | Select-Object -First 1
  $req = Join-Path $RepoDir "server\requirements.txt"
  Write-Warning "No Python on PATH can import the Agora deps (mcp + pydantic)."
  Write-Warning "Install them into the Python you'll use:  & `"$PY`" -m pip install -r `"$req`""
  Write-Warning "Proceeding with $PY so you can see the config, but the server will fail to start until deps are installed."
}

# ── Claude Desktop config location on Windows ─────────────────────────────────
$DesktopCfg = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"

Write-Host "──────────────────────────────────────────────────────────────"
Write-Host "Agora room (one literal path used everywhere):"
Write-Host "    $WS"
Write-Host "Server:  $Server"
Write-Host "Python:  $PY"
Write-Host "Desktop config: $DesktopCfg"
Write-Host "──────────────────────────────────────────────────────────────"

# ── Show the exact blocks (always) ────────────────────────────────────────────
$agora = [ordered]@{
  command = $PY
  args    = @($Server, "--workspace", $WS, "--name", "Agora")
}
Write-Host ""
Write-Host "Claude Desktop  ->  mcpServers.agora:"
($agora | ConvertTo-Json -Depth 10)
Write-Host ""
Write-Host "Claude Code  ->  equivalent registration:"
Write-Host "    claude mcp add agora -s user -- `"$PY`" `"$Server`" --workspace `"$WS`" --name Agora"
Write-Host ""

if ($Print -or $DryRun) {
  Write-Host "($(if ($Print) {'print'} else {'dry-run'}): no files changed.)"
  exit 0
}

# ── 1. Merge into Claude Desktop config (back up first, preserve existing) ─────
$cfgDir = Split-Path -Parent $DesktopCfg
New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
if (Test-Path -LiteralPath $DesktopCfg) {
  $bak = "$DesktopCfg.bak.$(Get-Date -Format yyyyMMdd-HHmmss)"
  Copy-Item -LiteralPath $DesktopCfg -Destination $bak
  Write-Host "Backed up existing Desktop config -> $bak"
  Write-Host "  (restore anytime:  Copy-Item `"$bak`" `"$DesktopCfg`" -Force)"
  try { $cfg = Get-Content -LiteralPath $DesktopCfg -Raw | ConvertFrom-Json }
  catch { Write-Error "existing $DesktopCfg is not valid JSON. Fix or move it, then re-run."; exit 1 }
} else {
  $cfg = [PSCustomObject]@{}
}

if (-not ($cfg.PSObject.Properties.Name -contains 'mcpServers')) {
  $cfg | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([PSCustomObject]@{})
}
$agoraObj = [PSCustomObject]@{
  command = $PY
  args    = @($Server, "--workspace", $WS, "--name", "Agora")
}
if ($cfg.mcpServers.PSObject.Properties.Name -contains 'agora') {
  $cfg.mcpServers.agora = $agoraObj
} else {
  $cfg.mcpServers | Add-Member -NotePropertyName agora -NotePropertyValue $agoraObj
}
$cfg | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $DesktopCfg -Encoding UTF8
Write-Host "Wrote agora -> $DesktopCfg"

# ── 2. Register with Claude Code (CLI if present, else print the command) ──────
$claude = Get-Command claude -ErrorAction SilentlyContinue
if ($claude) {
  & claude mcp remove agora -s user 2>$null
  & claude mcp add agora -s user -- $PY $Server --workspace $WS --name Agora
  Write-Host "Registered agora with Claude Code (user scope)."
} else {
  Write-Host "NOTE: 'claude' CLI not found in this shell — run this in your Claude Code:"
  Write-Host "    claude mcp add agora -s user -- `"$PY`" `"$Server`" --workspace `"$WS`" --name Agora"
}

# ── 3. Verify both surfaces carry the IDENTICAL literal path ───────────────────
Write-Host ""
Write-Host "Verifying both surfaces resolve to the same room..."
$check  = Get-Content -LiteralPath $DesktopCfg -Raw | ConvertFrom-Json
$dargs  = $check.mcpServers.agora.args
$deskWs = $dargs[[array]::IndexOf($dargs, "--workspace") + 1]
if ($deskWs -eq $WS) {
  Write-Host "  OK  Claude Desktop -> $deskWs"
} else {
  Write-Error "Claude Desktop path mismatch: $deskWs (expected $WS)"; exit 1
}
if ($claude) {
  $got = (& claude mcp get agora 2>$null | Out-String)
  if ($got -like "*$WS*") { Write-Host "  OK  Claude Code -> $WS" }
  else { Write-Host "  !   Claude Code registered, but couldn't confirm the path — check: claude mcp get agora" }
}

Write-Host ""
Write-Host "Done. Next:"
Write-Host "  1. Fully quit and reopen Claude Desktop (config is read at startup)."
Write-Host "  2. In Claude Code, run /agora-board (or ask it to call agora_board)."
Write-Host "  3. Prove the room: claim a task in one surface, try to claim it in the other"
Write-Host "     (must be refused), then hand it off. See CONNECT.md -> 'Verify the room'."
