"""Point the Twilio number at this machine's current public tunnel URL.

Reads the running ngrok agent's local API for the https public URL, then
updates the configured Twilio phone number's Voice webhook and status
callback. Because every launch re-points Twilio, free-tier ngrok's random
URLs stop mattering.

Usage:  venv/Scripts/python scripts/set_twilio_webhook.py   (prints the URL)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_settings  # noqa: E402

NGROK_API = "http://127.0.0.1:4040/api/tunnels"


def public_url() -> str:
    with urllib.request.urlopen(NGROK_API, timeout=5) as resp:
        data = json.load(resp)
    for tunnel in data.get("tunnels", []):
        url = tunnel.get("public_url", "")
        if url.startswith("https://"):
            return url
    raise SystemExit("no https tunnel found — is ngrok running? (ngrok http 8000)")


def main() -> None:
    from twilio.rest import Client

    settings = get_settings()
    # --url <public https url> skips the ngrok API (cloudflared quick tunnels
    # have no local API; the launcher hands the URL in directly).
    cli_url = None
    if "--url" in sys.argv:
        cli_url = sys.argv[sys.argv.index("--url") + 1]
    if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_phone_number):
        raise SystemExit("TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_PHONE_NUMBER must be set")

    url = cli_url or public_url()
    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    numbers = client.incoming_phone_numbers.list(phone_number=settings.twilio_phone_number)
    if not numbers:
        raise SystemExit(f"Twilio number {settings.twilio_phone_number} not found on this account")
    numbers[0].update(
        voice_url=f"{url}/voice/incoming",
        voice_method="POST",
        status_callback=f"{url}/voice/status",
        status_callback_method="POST",
    )
    # stdout contract: the last line is the base URL, consumed by launch.ps1.
    print(url)


if __name__ == "__main__":
    main()
