"""One-time Microsoft sign-in for the calendar (device-code flow).

Same mechanism career-ops' scan-email.mjs uses on the same mailbox: you get a
code, enter it at microsoft.com/devicelogin as scott@scottseverance.net, and
the refresh token lands at ``data/ms-token.json`` (gitignored).

Reuses the app registration the email scanner already has: MS_CLIENT_ID and
MS_TENANT_ID come from PDAgent's .env, or automatically from
``{career_ops_root}/.env`` (MICROSOFT_CLIENT_ID / MICROSOFT_TENANT_ID) when
PDAgent's are unset.

Usage:  venv/Scripts/python scripts/ms_auth.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_settings  # noqa: E402
from integrations.mscal import SCOPES, _save_token  # noqa: E402


def _post(url: str, form: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:  # pending-auth polls come back 400
        return json.load(exc)


def main() -> None:
    settings = get_settings()
    client_id, tenant = settings.ms_client_id, settings.ms_tenant_id
    if not client_id:
        raise SystemExit(
            "MS_CLIENT_ID is not set and no MICROSOFT_CLIENT_ID was found in the "
            "career-ops .env — set one of them first."
        )
    base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
    dc = _post(f"{base}/devicecode", {"client_id": client_id, "scope": SCOPES})
    if "device_code" not in dc:
        raise SystemExit(f"device-code request failed: {str(dc)[:300]}")
    print(f"\n{dc['message']}\n")

    interval = int(dc.get("interval", 5))
    deadline = time.time() + int(dc.get("expires_in", 900))
    while time.time() < deadline:
        time.sleep(interval)
        data = _post(f"{base}/token", {
            "client_id": client_id,
            "device_code": dc["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        })
        if "access_token" in data:
            _save_token({
                "access_token": data["access_token"],
                "refresh_token": data["refresh_token"],
            })
            print(f"\nAuthenticated. Token saved -> {settings.ms_token_path}")
            return
        err = data.get("error", "")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        raise SystemExit(f"sign-in failed: {err}: {str(data.get('error_description', ''))[:200]}")
    raise SystemExit("device code expired — run again")


if __name__ == "__main__":
    main()
