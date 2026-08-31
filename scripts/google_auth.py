"""One-time Google Calendar authorization for PDAgent.

Prereq: an OAuth client (Desktop app) from Google Cloud Console with the
Calendar API enabled, saved as ``data/google-client-secret.json``. Running
this opens a browser for consent and stores the refreshable token at
``data/google-token.json`` (both paths configurable in .env; both gitignored).

Usage:  venv/Scripts/python scripts/google_auth.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_settings  # noqa: E402
from integrations.gcal import SCOPES  # noqa: E402


def main() -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    settings = get_settings()
    secret = settings.google_client_secret_path
    if not os.path.exists(secret):
        raise SystemExit(
            f"Missing {secret}. In Google Cloud Console: enable the Calendar API, create "
            "an OAuth client of type 'Desktop app', download the JSON, and save it there."
        )
    flow = InstalledAppFlow.from_client_secrets_file(secret, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    os.makedirs(os.path.dirname(settings.google_token_path) or ".", exist_ok=True)
    with open(settings.google_token_path, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    print(f"token stored -> {settings.google_token_path}")


if __name__ == "__main__":
    main()
