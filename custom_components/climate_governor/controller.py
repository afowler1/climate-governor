"""Pure decision logic for a single room.

Nothing in here touches Home Assistant, so it can be unit tested directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum

UNAVAILABLE_STATES = ("unavailable", "unknown")

# Decision reasons (also surfaced on the status sensor)
R_SLEEP = "sleep_timer"
R_UNIT_UNAVAILABLE = "unit_unavailable"
R_NO_TEMPERATURE = "no_temperature"
R_OUTSIDE = "outside_profiles"
R_IN_BAND = "in_band"
R_HEATING = "heating"
R_COOLING = "cooling"
R_TARGET_REACHED = "target_reached"
R_MIN_ON = "min_on"
R_MIN_OFF = "min_off"
R_STARTED_HEAT = "started_heat"
R_STARTED_COOL = "started_cool"
R_OTHER_MODE = "unit_in_other_mode"


class HvacMode(StrEnum):
    """Modes the governor will command."""

    OFF = "off"
    HEAT = "heat"
    COOL = "cool"


class ActionKind(StrEnum):
    """What the caller should do."""

    NONE = "none"
    STOP = "stop"
    START = "start"


def in_window(now: time, start: time | None, end: time | None) -> bool:
    """Return True if `now` is inside the window. Windows may wrap midnight."""
    if start is None or end is None or start == end:
        return True
    if start < end:
        return start <= now < end
    return now >= start or now < end


@dataclass(frozen=True, slots=True)
class Profile:
    """A band of behaviour that is active when its gate is open."""

    name: str
    start_margin: float
    stop_margin: float
    overdrive: float = 0.0
    target_offset: float = 0.0
    window_start: time | None = None
    window_end: time | None = None
    requires_solar: bool = False

    def gate_open(self, now: time, solar_ok: bool) -> bool:
        """Return True if this profile applies right now."""
        if self.requires_solar and not solar_ok:
            return False
        return in_window(now, self.window_start, self.window_end)


@dataclass(frozen=True, slots=True)
class RoomSettings:
    """Static behaviour for a room. Profiles are in priority order."""

    profiles: tuple[Profile, ...]
    allow_heat: bool = True
    allow_cool: bool = True
    min_set: float = 18.0
    max_set: float = 27.0
    step: float = 1.0
    fan_mode: str | None = None
    min_on: timedelta = timedelta(minutes=5)
    min_off: timedelta = timedelta(minutes=5)
    stop_when_idle: bool = True


@dataclass(frozen=True, slots=True)
class Inputs:
    """A snapshot of the world for one evaluation."""

    now: datetime
    current: float | None
    target: float
    unit_mode: str
    solar_ok: bool = False
    sleep_active: bool = False
    last_change: datetime | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    """The result of one evaluation."""

    kind: ActionKind
    reason: str
    profile: str | None = None
    mode: HvacMode | None = None
    setpoint: float | None = None
    fan_mode: str | None = None


def active_profile(settings: RoomSettings, now: time, solar_ok: bool) -> Profile | None:
    """Return the first profile whose gate is open."""
    for profile in settings.profiles:
        if profile.gate_open(now, solar_ok):
            return profile
    return None


def snap(value: float, step: float, low: float, high: float) -> float:
    """Round to the unit's step, then clamp to its range."""
    if step > 0:
        value = round(value / step) * step
    return max(low, min(high, value))


def _elapsed(since: datetime | None, now: datetime, needed: timedelta) -> bool:
    """Return True if at least `needed` has passed since `since`."""
    return since is None or now - since >= needed


def _stop(settings: RoomSettings, inputs: Inputs, reason: str, profile: str | None) -> Decision:
    if not _elapsed(inputs.last_change, inputs.now, settings.min_on):
        return Decision(ActionKind.NONE, R_MIN_ON, profile)
    return Decision(ActionKind.STOP, reason, profile, HvacMode.OFF)


def _start(
    settings: RoomSettings, inputs: Inputs, profile: Profile, target: float, mode: HvacMode
) -> Decision:
    if not _elapsed(inputs.last_change, inputs.now, settings.min_off):
        return Decision(ActionKind.NONE, R_MIN_OFF, profile.name)
    if mode is HvacMode.HEAT:
        raw = target + profile.overdrive
        reason = R_STARTED_HEAT
    else:
        raw = target - profile.overdrive
        reason = R_STARTED_COOL
    setpoint = snap(raw, settings.step, settings.min_set, settings.max_set)
    return Decision(
        ActionKind.START, reason, profile.name, mode, setpoint, settings.fan_mode
    )


def decide(settings: RoomSettings, inputs: Inputs) -> Decision:
    """Work out what to do with the unit."""
    if inputs.sleep_active:
        return Decision(ActionKind.NONE, R_SLEEP)
    if inputs.unit_mode in UNAVAILABLE_STATES:
        return Decision(ActionKind.NONE, R_UNIT_UNAVAILABLE)

    running = inputs.unit_mode in (HvacMode.HEAT, HvacMode.COOL)
    profile = active_profile(settings, inputs.now.time(), inputs.solar_ok)

    if profile is None:
        if running and settings.stop_when_idle:
            return _stop(settings, inputs, R_OUTSIDE, None)
        return Decision(ActionKind.NONE, R_OUTSIDE)

    if inputs.current is None:
        return Decision(ActionKind.NONE, R_NO_TEMPERATURE, profile.name)

    target = inputs.target + profile.target_offset
    current = inputs.current

    if inputs.unit_mode == HvacMode.HEAT:
        if current >= target + profile.stop_margin:
            return _stop(settings, inputs, R_TARGET_REACHED, profile.name)
        return Decision(ActionKind.NONE, R_HEATING, profile.name)

    if inputs.unit_mode == HvacMode.COOL:
        if current <= target - profile.stop_margin:
            return _stop(settings, inputs, R_TARGET_REACHED, profile.name)
        return Decision(ActionKind.NONE, R_COOLING, profile.name)

    if inputs.unit_mode == HvacMode.OFF:
        if settings.allow_heat and current <= target - profile.start_margin:
            return _start(settings, inputs, profile, target, HvacMode.HEAT)
        if settings.allow_cool and current >= target + profile.start_margin:
            return _start(settings, inputs, profile, target, HvacMode.COOL)
        return Decision(ActionKind.NONE, R_IN_BAND, profile.name)

    return Decision(ActionKind.NONE, R_OTHER_MODE, profile.name)
