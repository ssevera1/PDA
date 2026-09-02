"""Calendar backend facade.

Scott's calendar is Exchange Online (Microsoft 365 via GoDaddy), so
``msgraph`` is the default; the Google backend stays available for anyone
running this against a Google calendar. The in-call tools import THIS module,
never a backend directly.
"""

from __future__ import annotations

from datetime import datetime

from config import get_settings
from agent.scheduling import Slot


def _backend():
    name = get_settings().calendar_backend
    if name == "google":
        from integrations import gcal

        return gcal
    from integrations import mscal

    return mscal


def fetch_busy(*, days: int, now: datetime | None = None) -> list[tuple[datetime, datetime]]:
    return _backend().fetch_busy(days=days, now=now)


def create_hold(slot: Slot, *, name: str, company: str, phone: str, email: str, topic: str) -> str:
    return _backend().create_hold(slot, name=name, company=company, phone=phone, email=email, topic=topic)
