# PDAgent watchdog: if the server or the public tunnel is dead, relaunch the
# whole stack (launch.ps1 re-points Twilio at the fresh tunnel URL). Meant to
# run from Task Scheduler every 15 minutes. Quick tunnels are ephemeral by
# nature; this is what turns "the tunnel dropped overnight" into a 15-minute
# blip instead of a dead phone line.
$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $PSScriptRoot

function Test-Health {
    try {
        $local = Invoke-RestMethod "http://127.0.0.1:8000/health" -TimeoutSec 5
        if ($local.status -ne "healthy") { return $false }
    } catch { return $false }
    # Public reachability: ask Twilio where the number points and probe it.
    try {
        $python = Join-Path $root "venv\Scripts\python.exe"
        $url = & $python -c "from config import get_settings; from twilio.rest import Client; s=get_settings(); c=Client(s.twilio_account_sid, s.twilio_auth_token); n=c.incoming_phone_numbers.list(phone_number=s.twilio_phone_number)[0]; print(n.voice_url)" 2>$null
        if (-not $url) { return $false }
        $base = ($url -replace "/voice/incoming$", "")
        $pub = Invoke-RestMethod "$base/health" -TimeoutSec 10
        return ($pub.status -eq "healthy")
    } catch { return $false }
}

Set-Location $root
if (Test-Health) { exit 0 }

Write-Output "$(Get-Date -Format s) unhealthy — relaunching"
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*PDAgent*" } | Stop-Process -Force -Confirm:$false
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -Confirm:$false
Start-Sleep -Seconds 2

# Alert, then relaunch (launch.ps1 blocks on uvicorn, so run it detached).
try {
    $python = Join-Path $root "venv\Scripts\python.exe"
    & $python -c "import asyncio; from notifications.telegram import send_live; asyncio.run(send_live('PDAgent watchdog: stack was down, relaunching now.'))" 2>$null
} catch {}
Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $root "scripts\launch.ps1") -WindowStyle Hidden
