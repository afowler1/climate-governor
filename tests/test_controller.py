"""Tests for the pure controller logic."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from custom_components.climate_governor.controller import (
    ActionKind,
    HvacMode,
    Inputs,
    Profile,
    RoomSettings,
    decide,
    in_window,
    snap,
)

TZ = timezone(timedelta(hours=10))


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 5, hour, minute, tzinfo=TZ)


NIGHT = Profile(
    name="overnight",
    start_margin=5,
    stop_margin=0,
    overdrive=2,
    window_start=time(21, 0),
    window_end=time(6, 0),
)
SOLAR = Profile(
    name="solar",
    start_margin=1,
    stop_margin=0.5,
    target_offset=-1,
    window_start=time(9, 0),
    window_end=time(16, 0),
    requires_solar=True,
)


def settings(*profiles: Profile, **kwargs) -> RoomSettings:
    return RoomSettings(profiles=profiles or (NIGHT,), **kwargs)


def inputs(hour: int = 23, current: float | None = 26, **kwargs) -> Inputs:
    base = {"now": at(hour), "current": current, "target": 26.0, "unit_mode": "off"}
    base.update(kwargs)
    return Inputs(**base)


def test_window_wraps_midnight() -> None:
    assert in_window(time(23, 0), time(21, 0), time(6, 0))
    assert in_window(time(2, 0), time(21, 0), time(6, 0))
    assert not in_window(time(12, 0), time(21, 0), time(6, 0))
    assert not in_window(time(6, 0), time(21, 0), time(6, 0))


def test_window_without_bounds_is_always_open() -> None:
    assert in_window(time(12, 0), None, None)


def test_snap_rounds_and_clamps() -> None:
    assert snap(24.4, 1, 18, 27) == 24
    assert snap(28, 1, 18, 27) == 27
    assert snap(10, 1, 18, 27) == 18
    assert snap(24.3, 0.5, 18, 27) == 24.5


def test_in_band_does_nothing() -> None:
    decision = decide(settings(), inputs(current=28))
    assert decision.kind is ActionKind.NONE
    assert decision.reason == "in_band"


def test_cool_starts_with_overdrive() -> None:
    decision = decide(settings(), inputs(current=31))
    assert decision.kind is ActionKind.START
    assert decision.mode is HvacMode.COOL
    assert decision.setpoint == 24


def test_heat_setpoint_is_clamped_to_unit_maximum() -> None:
    decision = decide(settings(), inputs(current=21))
    assert decision.mode is HvacMode.HEAT
    assert decision.setpoint == 27


def test_target_above_unit_maximum_is_clamped() -> None:
    night = Profile(
        name="overnight",
        start_margin=8,
        stop_margin=5,
        window_start=time(21, 0),
        window_end=time(6, 0),
    )
    decision = decide(settings(night), inputs(current=37, target=29))
    assert decision.mode is HvacMode.COOL
    assert decision.setpoint == 27


def test_respects_allowed_modes() -> None:
    assert decide(settings(allow_heat=False), inputs(current=20)).kind is ActionKind.NONE
    assert decide(settings(allow_cool=False), inputs(current=32)).kind is ActionKind.NONE


def test_heating_stops_at_target() -> None:
    running = inputs(current=26, unit_mode="heat")
    assert decide(settings(), running).kind is ActionKind.STOP
    assert decide(settings(), inputs(current=25, unit_mode="heat")).reason == "heating"


def test_cooling_stops_at_target() -> None:
    assert decide(settings(), inputs(current=26, unit_mode="cool")).kind is ActionKind.STOP
    assert decide(settings(), inputs(current=27, unit_mode="cool")).reason == "cooling"


def test_stops_when_window_ends() -> None:
    decision = decide(settings(), inputs(hour=7, unit_mode="cool", owned=True))
    assert decision.kind is ActionKind.STOP
    assert decision.reason == "outside_profiles"


def test_manual_run_outside_window_is_left_alone() -> None:
    decision = decide(settings(), inputs(hour=14, unit_mode="cool", owned=False))
    assert decision.kind is ActionKind.NONE
    assert decision.reason == "outside_profiles"


def test_leaves_unit_alone_outside_window_if_configured() -> None:
    decision = decide(settings(stop_when_idle=False), inputs(hour=7, unit_mode="cool", owned=True))
    assert decision.kind is ActionKind.NONE


def test_idle_outside_window_does_nothing() -> None:
    assert decide(settings(), inputs(hour=12, current=35)).kind is ActionKind.NONE


def test_sleep_timer_pauses_control() -> None:
    decision = decide(settings(), inputs(current=35, sleep_active=True))
    assert decision.kind is ActionKind.NONE
    assert decision.reason == "sleep_timer"


def test_missing_temperature_does_nothing() -> None:
    decision = decide(settings(), inputs(current=None))
    assert decision.kind is ActionKind.NONE
    assert decision.reason == "no_temperature"


def test_unavailable_unit_does_nothing() -> None:
    assert decide(settings(), inputs(current=35, unit_mode="unavailable")).kind is ActionKind.NONE


def test_other_modes_are_left_alone() -> None:
    decision = decide(settings(), inputs(current=35, unit_mode="dry"))
    assert decision.kind is ActionKind.NONE
    assert decision.reason == "unit_in_other_mode"


def test_min_on_defers_stop() -> None:
    recent = at(22, 58)
    decision = decide(settings(), inputs(current=26, unit_mode="cool", last_change=recent))
    assert decision.kind is ActionKind.NONE
    assert decision.reason == "min_on"


def test_min_off_defers_start() -> None:
    recent = at(22, 58)
    decision = decide(settings(), inputs(current=31, last_change=recent))
    assert decision.kind is ActionKind.NONE
    assert decision.reason == "min_off"


def test_solar_profile_needs_solar_gate() -> None:
    cfg = settings(NIGHT, SOLAR)
    closed = decide(cfg, inputs(hour=12, current=28, solar_ok=False))
    assert closed.kind is ActionKind.NONE
    assert closed.profile is None
    opened = decide(cfg, inputs(hour=12, current=28, solar_ok=True))
    assert opened.kind is ActionKind.START
    assert opened.profile == "solar"
    # target 26 + offset -1 = 25; cooling starts at 26, setpoint is 25
    assert opened.setpoint == 25


def test_solar_stops_when_gate_closes() -> None:
    cfg = settings(NIGHT, SOLAR)
    decision = decide(cfg, inputs(hour=12, current=25, unit_mode="cool", solar_ok=False, owned=True))
    assert decision.kind is ActionKind.STOP


def test_first_open_profile_wins() -> None:
    always = Profile(name="a", start_margin=1, stop_margin=0)
    other = Profile(name="b", start_margin=9, stop_margin=0)
    decision = decide(settings(always, other), inputs(current=28))
    assert decision.profile == "a"


def test_fan_mode_is_passed_through() -> None:
    decision = decide(settings(fan_mode="low"), inputs(current=31))
    assert decision.fan_mode == "low"
