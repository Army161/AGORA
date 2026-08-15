<#
  verify-connector.ps1 — check that a running Agora web connector is actually
  reachable and speaks OAuth 2.1 correctly, before you hand the URL to a surface
  (or to an audience).

  A Custom Connector fails for boring reasons: the tunnel died, the server is
  advertising a stale public URL, or the discovery chain is broken. Each of those
  shows up in a browser as the same unhelpful "could not connect". This walks the
  exact chain claude.ai walks and says which link is broken.

  Usage:
    .\verify-connector.ps1 -PublicUrl "https://your-stable-url.ngrok-free.app"

  Runs on both Windows PowerShell 5.1 and PowerShell 7+.
  Exit code 0 = every check passed and the URL is safe to hand out.
#>
param(
  [Parameter(Mandatory=$true)]
  [string]$PublicUrl,
  [int]$TimeoutSec = 20
)

$PublicUrl = $PublicUrl.TrimEnd('/')
$mcp       = "$PublicUrl/mcp"
$script:failures = 0
$script:warnings = 0

function Step($n, $text) { Write-Host ""; Write-Host "[$n] $text" -ForegroundColor Cyan }
function Pass($text)     { Write-Host "    PASS  $text" -ForegroundColor Green }
function Fail($text)     { Write-Host "    FAIL  $text" -ForegroundColor Red;    $script:failures++ }
function Warn($text)     { Write-Host "    WARN  $text" -ForegroundColor Yellow; $script:warnings++ }

# Response headers differ by PowerShell edition: 5.1 hands back an
# HttpWebResponse (indexable), 7+ hands back an HttpResponseMessage (not
# indexable — it needs TryGetValues). Read both rather than assuming one, or the
# check reports a missing header that is demonstrably present.
function Get-ResponseHeader($response, [string]$name) {
  if ($null -eq $response) { return $null }
  $headers = $response.Headers
  if ($null -eq $headers) { return $null }
  try {
    $values = $null
    if ($headers.TryGetValues($name, [ref]$values)) { return ($values -join ', ') }
  } catch { }
  try {
    $v = $headers[$name]
    if ($v) { return ($v -join ', ') }
  } catch { }
  return $null
}

function Get-StatusCode($response) {
  if ($null -eq $response) { return $null }
  try { return [int]$response.StatusCode } catch { return $null }
}

Write-Host ""
Write-Host "Verifying Agora connector at $PublicUrl" -ForegroundColor White

# -- 1. The MCP endpoint must reject anonymous callers, and say where to authenticate --
# A 200 here would mean the room is open to anyone who finds the URL.
Step 1 "MCP endpoint rejects unauthenticated requests"
$resourceMeta = $null
try {
  $body = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"verify","version":"1"}}}'
  Invoke-WebRequest -Uri $mcp -Method POST -Body $body -ContentType "application/json" `
                    -Headers @{ Accept = "application/json, text/event-stream" } `
                    -UseBasicParsing -TimeoutSec $TimeoutSec -ErrorAction Stop | Out-Null
  Fail "$mcp returned 200 without a token - the room is publicly readable. Stop the server."
} catch {
  $resp = $_.Exception.Response
  $code = Get-StatusCode $resp
  if ($code -eq 401) {
    Pass "401 Unauthorized (correct)"
    $wwwAuth = Get-ResponseHeader $resp "WWW-Authenticate"
    if ($wwwAuth) {
      Pass "WWW-Authenticate present"
      # RFC 9728 scopes this document per-resource, so the path carries the
      # resource's own suffix (.../oauth-protected-resource/mcp). Trust the
      # header rather than guessing the URL - guessing returns a misleading 404.
      if ($wwwAuth -match 'resource_metadata="([^"]+)"') {
        $resourceMeta = $Matches[1]
        Pass "advertises resource metadata -> $resourceMeta"
      } else {
        Warn "no resource_metadata hint; clients must guess the discovery URL"
      }
    } else {
      Fail "no WWW-Authenticate header - clients cannot discover where to authenticate"
    }
  } elseif ($null -eq $code) {
    Fail "unreachable: $($_.Exception.Message)  (tunnel down, or wrong URL?)"
  } else {
    Fail "expected 401, got $code"
  }
}

# -- 2. The advertised protected-resource document must resolve --
Step 2 "Protected-resource metadata resolves"
if ($resourceMeta) {
  try {
    $doc = (Invoke-WebRequest -Uri $resourceMeta -UseBasicParsing -TimeoutSec $TimeoutSec).Content | ConvertFrom-Json
    Pass "200 OK"
    if ($doc.resource -eq $mcp) {
      Pass "resource matches $mcp"
    } else {
      Fail "resource is '$($doc.resource)' but should be '$mcp' - stale --public-url?"
    }
    if ($doc.authorization_servers) {
      Pass "authorization server -> $($doc.authorization_servers[0])"
    } else {
      Fail "no authorization_servers listed"
    }
  } catch {
    Fail "could not fetch $resourceMeta : $($_.Exception.Message)"
  }
} else {
  Warn "skipped (nothing advertised in step 1)"
}

# -- 3. The authorization server must offer DCR and PKCE --
# claude.ai has nowhere to paste a token: it self-registers, so both are required.
Step 3 "Authorization server supports Dynamic Client Registration + PKCE"
try {
  $as = (Invoke-WebRequest -Uri "$PublicUrl/.well-known/oauth-authorization-server" `
                           -UseBasicParsing -TimeoutSec $TimeoutSec).Content | ConvertFrom-Json
  Pass "200 OK"

  if ($as.registration_endpoint) {
    Pass "registration endpoint (DCR) present"
  } else {
    Fail "no registration_endpoint - surfaces cannot self-register"
  }

  if ($as.code_challenge_methods_supported -contains "S256") {
    Pass "PKCE S256 supported"
  } else {
    Fail "PKCE S256 not advertised"
  }

  # The single most common failure: server restarted behind a new tunnel URL and
  # is still advertising the old one. Every redirect then lands nowhere.
  $endpoints = @(
    @{ n = "issuer";        v = $as.issuer },
    @{ n = "authorization"; v = $as.authorization_endpoint },
    @{ n = "token";         v = $as.token_endpoint }
  )
  foreach ($pair in $endpoints) {
    if ($pair.v -and $pair.v.StartsWith($PublicUrl)) {
      Pass "$($pair.n) endpoint on this host"
    } else {
      Fail "$($pair.n) endpoint is '$($pair.v)' - server is advertising a stale public URL. Restart it with the current --public-url."
    }
  }
} catch {
  Fail "could not fetch authorization server metadata: $($_.Exception.Message)"
}

# -- verdict --
Write-Host ""
if ($script:failures -eq 0) {
  Write-Host "READY - $($script:failures) failed, $($script:warnings) warning(s)." -ForegroundColor Green
  Write-Host ""
  Write-Host "Add this as a Custom Connector:" -ForegroundColor White
  Write-Host "    $mcp" -ForegroundColor Cyan
  exit 0
} else {
  Write-Host "NOT READY - $($script:failures) check(s) failed, $($script:warnings) warning(s)." -ForegroundColor Red
  Write-Host "Do not hand this URL out until the failures above are fixed." -ForegroundColor Red
  exit 1
}
