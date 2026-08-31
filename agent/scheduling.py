"""Slot proposal rules for in-call scheduling.

Pure logic: Google free/busy intervals in, bookable slots out. Nothing here
touches the network or the calendar; ``integrations/gcal.py`` supplies the
busy list and books the winner. Keeping this pure is what makes the rules
testable to the minute.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class SchedulingRules:
    """Bookable-time policy. All times are wall-clock in ``timezone``."""

    timezone: str = "America/Chicago"
    work_start: time = time(9, 0)
    work_end: time = time(17, 30)
    evening_end: time = time(20, 0)  # evening window runs work_end -> evening_end
    include_evenings: bool = True
    slot_minutes: int = 30
    buffer_minutes: int = 30  # clearance required around existing events
    min_lead_hours: int = 24  # never offer anything sooner than this
    horizon_days: int = 7  # calendar days scanned (weekends skipped)
    max_slots: int = 3

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime

    def spoken(self) -> str:
        """A form Sophie can say aloud: 'Tuesday September first at two thirty PM Central'."""
        day = self.start.strftime("%A %B %d").replace(" 0", " ")
        clock = self.start.strftime("%I:%M %p").lstrip("0")
        return f"{day} at {clock} Central"


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def propose_slots(
    busy: list[tuple[datetime, datetime]],
    *,
    now: datetime,
    rules: SchedulingRules | None = None,
) -> list[Slot]:
    """Bookable slots given the calendar's busy intervals.

    ``busy`` and ``now`` must be timezone-aware. Slots start on the half hour,
    respect the work and evening windows on weekdays only, keep
    ``buffer_minutes`` clear on both sides of every busy interval, and never
    start before ``now + min_lead_hours``. The result spreads across days:
    the earliest slot of each distinct day is offered first, then second
    choices, up to ``max_slots``.
    """
    r = rules or SchedulingRules()
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    for b_start, b_end in busy:
        if b_start.tzinfo is None or b_end.tzinfo is None:
            raise ValueError("busy intervals must be timezone-aware")

    tz = r.tz
    local_now = now.astimezone(tz)
    earliest = local_now + timedelta(hours=r.min_lead_hours)
    slot_len = timedelta(minutes=r.slot_minutes)
    buffer = timedelta(minutes=r.buffer_minutes)
    day_end = r.evening_end if r.include_evenings else r.work_end

    candidates: list[Slot] = []
    for day_offset in range(r.horizon_days + 1):
        day = (local_now + timedelta(days=day_offset)).date()
        if day.weekday() >= 5:  # Saturday/Sunday
            continue
        cursor = datetime.combine(day, r.work_start, tzinfo=tz)
        end_of_day = datetime.combine(day, day_end, tzinfo=tz)
        while cursor + slot_len <= end_of_day:
            start, end = cursor, cursor + slot_len
            cursor += timedelta(minutes=30)
            if start < earliest:
                continue
            padded_start, padded_end = start - buffer, end + buffer
            if any(_overlaps(padded_start, padded_end, b.astimezone(tz), e.astimezone(tz)) for b, e in busy):
                continue
            candidates.append(Slot(start, end))

    # Spread across days: first pick of each day, then second picks, and so on.
    by_day: dict[object, list[Slot]] = {}
    for slot in candidates:
        by_day.setdefault(slot.start.date(), []).append(slot)
    picked: list[Slot] = []
    rank = 0
    while len(picked) < r.max_slots:
        added = False
        for day in sorted(by_day):
            slots = by_day[day]
            if rank < len(slots) and len(picked) < r.max_slots:
                picked.append(slots[rank])
                added = True
        if not added:
            break
        rank += 1
    return sorted(picked, key=lambda s: s.start)
