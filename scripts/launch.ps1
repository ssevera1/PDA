# PDAgent launcher: tunnel up -> Twilio webhook re-pointed -> server up.
# Tunnel provider: ngrok when an authtoken is configured, otherwise a
# cloudflared quick tunnel (no account needed). Either way the Twilio number
# is re-pointed at the fresh public URL on every launch, so ephemeral tunnel
# hostnames don't matter.
#   powershell -ExecutionPolicy Bypass -File scripts\launch.ps1
param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root "venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "venv not found at $python" }

$baseUrl = $null

# --- Option A: ngrok (only if an authtoken is configured) --------------------
$ngrokReady = $false
try { ngrok config check *> $null; if ($LASTEXITCODE -eq 0) { $ngrokReady = $true } } catch {}
if ($ngrokReady) {
    $up = $false
    try { Invoke-RestMethod "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 2 | Out-Null; $up = $true } catch {}
    if (-not $up) {
        Start-Process ngrok -ArgumentList "http", "$Port" -WindowStyle Hidden
        $deadline = (Get-Date).AddSeconds(30)
        while ((Get-Date) -lt $deadline -and -not $up) {
            Start-Sleep -Seconds 1
            try { Invoke-RestMethod "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 2 | Out-Null; $up = $true } catch {}
        }
    }
    if ($up) {
        $tunnels = Invoke-RestMethod "http://127.0.0.1:4040/api/tunnels"
        $baseUrl = ($tunnels.tunnels | Where-Object { $_.public_url -like "https://*" } | Select-Object -First 1).public_url
        Write-Output "ngrok tunnel: $baseUrl"
    }
}

# --- Option B: cloudflared quick tunnel (no account) -------------------------
if (-not $baseUrl) {
    $cf = "cloudflared"
    if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
        $candidates = @("C:\Program Files (x86)\cloudflared\cloudflared.exe", "C:\Program Files\cloudflared\cloudflared.exe")
        $cf = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $cf) { throw "No tunnel available: configure ngrok (ngrok config add-authtoken ...) or install cloudflared" }
    }
    $log = Join-Path $root "data\automation-logs\cloudflared.log"
    New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
    if (Test-Path $log) { Clear-Content $log }
    Start-Process $cf -ArgumentList "tunnel", "--url", "http://localhost:$Port", "--no-autoupdate", "--logfile", $log -WindowStyle Hidden
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline -and -not $baseUrl) {
        Start-Sleep -Seconds 2
        if (Test-Path $log) {
            $match = Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -AllMatches | Select-Object -First 1
            if ($match) { $baseUrl = $match.Matches[0].Value }
        }
    }
    if (-not $baseUrl) { throw "cloudflared quick tunnel did not report a URL within 45s (see $log)" }
    Write-Output "cloudflared quick tunnel: $baseUrl"
}

# --- Re-point the Twilio number, then start the server -----------------------
$confirmed = (& $python "scripts\set_twilio_webhook.py" "--url" $baseUrl | Select-Object -Last 1).Trim()
if (-not $confirmed.StartsWith("https://")) { throw "webhook script did not confirm a URL: $confirmed" }
Write-Output "Twilio webhook -> $confirmed"

$env:BASE_URL = $confirmed
& $python -m uvicorn main:app --host 0.0.0.0 --port $Port
