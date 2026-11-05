"""Tests for the solar budget helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from custom_components.climate_governor.solar import (
    RollingAverage,
    SolarRoom,
    solar_allowed,
)

TZ = timezone(timedelta(hours=10))
T0 = datetime(2026, 11, 5, 12, 0, tzinfo=TZ)


def room(room_id: str, priority: int, load: float, running: bool = False) -> SolarRoom:
    return SolarRoom(room_id, priority, load, running)


def test_single_room_fits_within_export() -> None:
    rooms = [room("down", 1, 2000)]
    assert solar_allowed("down", rooms, 3200, 200)


def test_single_room_too_big_for_export() -> None:
    rooms = [room("down", 1, 2000)]
    assert not solar_allowed("down", rooms, 1500, 200)


def test_no_reading_means_no_solar() -> None:
    assert not solar_allowed("down", [room("down", 1, 100)], None, 0)


def test_priority_order_shares_the_budget() -> None:
    rooms = [room("down", 1, 2000, True), room("office", 2, 1500)]
    # export 3200 already reflects the running room's draw
    assert not solar_allowed("office", rooms, 1000, 200)
    assert solar_allowed("office", rooms, 2000, 200)


def test_running_room_keeps_its_own_load_in_budget() -> None:
    rooms = [room("down", 1, 2000, True)]
    assert solar_allowed("down", rooms, 0, 200)


def test_higher_priority_room_can_displace_lower() -> None:
    rooms = [room("down", 1, 2000), room("office", 2, 1500, True)]
    assert solar_allowed("down", rooms, 600, 200)
    # once down is running, office no longer fits
    rooms = [room("down", 1, 2000, True), room("office", 2, 1500, True)]
    assert not solar_allowed("office", rooms, 100, 200)


def test_unknown_room_is_not_allowed() -> None:
    assert not solar_allowed("ghost", [room("down", 1, 100)], 5000, 0)


def test_rolling_average_over_window() -> None:
    avg = RollingAverage(timedelta(minutes=5))
    avg.add(T0, 1000)
    avg.add(T0 + timedelta(minutes=1), 2000)
    assert avg.average(T0 + timedelta(minutes=1)) == 1500


def test_rolling_average_drops_old_samples() -> None:
    avg = RollingAverage(timedelta(minutes=5))
    avg.add(T0, 1000)
    avg.add(T0 + timedelta(minutes=6), 3000)
    assert avg.average(T0 + timedelta(minutes=6)) == 3000


def test_rolling_average_empty_after_silence() -> None:
    avg = RollingAverage(timedelta(minutes=5))
    avg.add(T0, 1000)
    assert avg.average(T0 + timedelta(minutes=10)) is None
