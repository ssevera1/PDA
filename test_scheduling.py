"""Unit tests for the pure slot-proposal rules."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from agent.scheduling import SchedulingRules, Slot, propose_slots

CT = ZoneInfo("America/Chicago")
# A Monday morning, so the whole business week is ahead of us.
NOW = datetime(2026, 8, 31, 8, 0, tzinfo=CT)  # Mon Aug 31 2026, 8:00 CT
RULES = SchedulingRules()


def _starts(slots: list[Slot]) -> list[datetime]:
    return [s.start for s in slots]


def test_empty_calendar_gives_three_slots_spread_across_days():
    slots = propose_slots([], now=NOW, rules=RULES)
    assert len(slots) == 3
    days = {s.start.date() for s in slots}
    assert len(days) == 3, f"slots should spread across days, got {days}"


def test_lead_time_is_respected():
    slots = propose_slots([], now=NOW, rules=RULES)
    for s in slots:
        assert s.start >= NOW + timedelta(hours=RULES.min_lead_hours)


def test_slots_fall_inside_bookable_windows_on_weekdays():
    slots = propose_slots([], now=NOW, rules=SchedulingRules(max_slots=30, horizon_days=10))
    assert slots
    for s in slots:
        assert s.start.weekday() < 5
        assert time(9, 0) <= s.start.time()
        assert s.end.time() <= time(20, 0) or s.end.time() == time(0, 0)


def test_evenings_can_be_disabled():
    rules = SchedulingRules(include_evenings=False, max_slots=50)
    slots = propose_slots([], now=NOW, rules=rules)
    assert slots
    for s in slots:
        assert s.end.time() <= time(17, 30)


def test_busy_interval_blocks_slot_and_buffer_around_it():
    # Tuesday 10:00-11:00 busy; with a 30-minute buffer, 9:00 is the last
    # bookable morning start (9:00-9:30 ends 30 min before the meeting) and
    # 11:30 the first after it.
    busy_start = datetime(2026, 9, 1, 10, 0, tzinfo=CT)
    busy = [(busy_start, busy_start + timedelta(hours=1))]
    rules = SchedulingRules(max_slots=100, horizon_days=1)
    slots = propose_slots(busy, now=NOW, rules=rules)
    tuesday = [s for s in slots if s.start.date() == busy_start.date()]
    assert tuesday, "Tuesday should still have open slots"
    for s in tuesday:
        assert not (busy_start - timedelta(minutes=30) < s.end and s.start < busy_start + timedelta(hours=1, minutes=30)), (
            f"slot {s.start:%H:%M} violates the buffer"
        )
    starts = {s.start.time() for s in tuesday}
    assert time(9, 0) in starts
    assert time(9, 30) not in starts  # would end 10:00, inside the buffer
    assert time(11, 0) not in starts
    assert time(11, 30) in starts


def test_fully_booked_horizon_gives_no_slots():
    # One busy block swallowing every weekday window in the horizon.
    busy = [(
        datetime(2026, 8, 31, 0, 0, tzinfo=CT),
        datetime(2026, 9, 30, 0, 0, tzinfo=CT),
    )]
    assert propose_slots(busy, now=NOW, rules=RULES) == []


def test_no_weekend_slots():
    # Friday afternoon: with a 24h lead the next candidates land Sat/Sun,
    # which must be skipped in favor of Monday.
    friday = datetime(2026, 9, 4, 15, 0, tzinfo=CT)
    slots = propose_slots([], now=friday, rules=RULES)
    assert slots
    for s in slots:
        assert s.start.weekday() < 5


def test_utc_busy_intervals_are_converted():
    # 15:00 UTC == 10:00 CT during CDT; same expectation as the CT test.
    busy_start_utc = datetime(2026, 9, 1, 15, 0, tzinfo=ZoneInfo("UTC"))
    busy = [(busy_start_utc, busy_start_utc + timedelta(hours=1))]
    rules = SchedulingRules(max_slots=100, horizon_days=1)
    starts = {s.start.time() for s in propose_slots(busy, now=NOW, rules=rules)}
    assert time(10, 0) not in starts
    assert time(11, 30) in starts


def test_naive_datetimes_are_rejected():
    import pytest

    with pytest.raises(ValueError):
        propose_slots([], now=datetime(2026, 8, 31, 8, 0), rules=RULES)
    with pytest.raises(ValueError):
        propose_slots(
            [(datetime(2026, 9, 1, 10, 0), datetime(2026, 9, 1, 11, 0))],
            now=NOW,
            rules=RULES,
        )


def test_spoken_form_has_no_leading_zero_and_names_the_day():
    slot = Slot(
        start=datetime(2026, 9, 1, 14, 30, tzinfo=CT),
        end=datetime(2026, 9, 1, 15, 0, tzinfo=CT),
    )
    text = slot.spoken()
    assert "Tuesday" in text and "2:30 PM Central" in text
    assert " 0" not in text
