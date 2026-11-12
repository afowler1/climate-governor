"""Home Assistant glue around the pure controller."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import Callable, Mapping
from datetime import time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_ALLOW_COOL,
    CONF_ALLOW_HEAT,
    CONF_CLIMATE,
    CONF_DEFAULT_TARGET,
    CONF_ENABLED,
    CONF_EST_LOAD_W,
    CONF_EXPORT_SENSOR,
    CONF_FAN_MODE,
    CONF_MAX_SENSOR_AGE,
    CONF_MAX_SET,
    CONF_MIN_OFF,
    CONF_MIN_ON,
    CONF_MIN_SET,
    CONF_OVERDRIVE,
    CONF_PROFILE_HEAT,
    CONF_PRIORITY,
    CONF_RESERVE_W,
    CONF_SLEEP_TIMER,
    CONF_SMOOTHING_MINUTES,
    CONF_START_MARGIN,
    CONF_STOP_MARGIN,
    CONF_TARGET_OFFSET,
    CONF_TEMP_SENSOR,
    CONF_WINDOW_END,
    CONF_WINDOW_START,
    DEFAULT_MAX_SENSOR_AGE,
    DEFAULT_MIN_OFF,
    DEFAULT_MIN_ON,
    DEFAULT_RESERVE_W,
    DEFAULT_SMOOTHING_MINUTES,
    DEFAULT_TARGET,
    EVALUATE_INTERVAL_SECONDS,
    PROFILE_OVERNIGHT,
    PROFILE_SOLAR,
    STATUS_COOLING,
    STATUS_DISABLED,
    STATUS_HEATING,
    STATUS_IDLE,
    STATUS_SLEEP,
    STATUS_WAITING,
)
from .controller import (
    ActionKind,
    Decision,
    HvacMode,
    Inputs,
    Profile,
    RoomSettings,
    band,
    band_summary,
    decide,
    next_profile,
    profile_window,
    R_MIN_OFF,
    R_SLEEP,
)
from .solar import RollingAverage, SolarRoom, solar_allowed

_LOGGER = logging.getLogger(__name__)

UNAVAILABLE = ("unavailable", "unknown")
RUNNING_MODES = (HvacMode.HEAT.value, HvacMode.COOL.value)
HA_DEFAULT_MIN_TEMP = 7.0
HA_DEFAULT_MAX_TEMP = 35.0
STORAGE_VERSION = 1
SAVE_DELAY_SECONDS = 5


def _store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")


async def async_remove_store(hass: HomeAssistant, entry_id: str) -> None:
    """Delete the saved room state when the entry is removed."""
    await _store(hass, entry_id).async_remove()


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_time(value: Any) -> time | None:
    if not value:
        return None
    try:
        return time.fromisoformat(str(value))
    except ValueError:
        return None


def _profile(data: Mapping[str, Any], name: str, requires_solar: bool) -> Profile | None:
    def key(field: str) -> str:
        return f"{name}_{field}"

    if not data.get(key(CONF_ENABLED), False):
        return None
    return Profile(
        name=name,
        start_margin=_number(data.get(key(CONF_START_MARGIN)), 2.0),
        stop_margin=_number(data.get(key(CONF_STOP_MARGIN)), 0.0),
        overdrive=_number(data.get(key(CONF_OVERDRIVE)), 0.0),
        target_offset=_number(data.get(key(CONF_TARGET_OFFSET)), 0.0),
        window_start=_parse_time(data.get(key(CONF_WINDOW_START))),
        window_end=_parse_time(data.get(key(CONF_WINDOW_END))),
        requires_solar=requires_solar,
        allow_heat=bool(data.get(key(CONF_PROFILE_HEAT), True)),
    )


def build_settings(data: Mapping[str, Any]) -> RoomSettings:
    """Turn stored room data into controller settings."""
    candidates = (
        _profile(data, PROFILE_OVERNIGHT, False),
        _profile(data, PROFILE_SOLAR, True),
    )
    return RoomSettings(
        profiles=tuple(p for p in candidates if p is not None),
        allow_heat=bool(data.get(CONF_ALLOW_HEAT, True)),
        allow_cool=bool(data.get(CONF_ALLOW_COOL, True)),
        min_set=_number(data.get(CONF_MIN_SET), HA_DEFAULT_MIN_TEMP),
        max_set=_number(data.get(CONF_MAX_SET), HA_DEFAULT_MAX_TEMP),
        fan_mode=data.get(CONF_FAN_MODE) or None,
        min_on=timedelta(minutes=_number(data.get(CONF_MIN_ON), DEFAULT_MIN_ON)),
        min_off=timedelta(minutes=_number(data.get(CONF_MIN_OFF), DEFAULT_MIN_OFF)),
    )


class SolarHub:
    """Tracks exported solar power and shares it between rooms."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry_id = entry.entry_id
        self._listeners: list[Callable[[], None]] = []
        self.export_sensor: str | None = entry.data.get(CONF_EXPORT_SENSOR) or None
        self.reserve_w = _number(entry.data.get(CONF_RESERVE_W), DEFAULT_RESERVE_W)
        minutes = _number(entry.data.get(CONF_SMOOTHING_MINUTES), DEFAULT_SMOOTHING_MINUTES)
        self._average = RollingAverage(timedelta(minutes=minutes))
        self.rooms: dict[str, RoomRunner] = {}
        self._unsubs: list[Callable[[], None]] = []
        self._store = _store(hass, entry.entry_id)
        # Room state saved before the last restart, keyed by room id.
        self.saved: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        """Load the room state saved before the last restart."""
        data = await self._store.async_load()
        self.saved = (data or {}).get("rooms", {})

    @callback
    def schedule_save(self) -> None:
        """Save room state shortly (also flushed when Home Assistant stops)."""
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY_SECONDS)

    async def async_save(self) -> None:
        """Save room state now, e.g. before a reload."""
        await self._store.async_save(self._data_to_save())

    @callback
    def _data_to_save(self) -> dict[str, Any]:
        return {"rooms": {room_id: r.persisted() for room_id, r in self.rooms.items()}}

    async def async_start(self) -> None:
        """Begin sampling the export sensor."""
        if not self.export_sensor:
            return
        self._sample()
        self._unsubs.append(
            async_track_state_change_event(self.hass, [self.export_sensor], self._on_change)
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._on_tick, timedelta(seconds=EVALUATE_INTERVAL_SECONDS)
            )
        )

    @callback
    def async_stop(self) -> None:
        """Stop sampling."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def _sample(self) -> None:
        if not self.export_sensor:
            return
        state = self.hass.states.get(self.export_sensor)
        if state is None or state.state in UNAVAILABLE:
            return
        try:
            value = float(state.state)
        except ValueError:
            return
        self._average.add(dt_util.utcnow(), value)

    @callback
    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register an entity callback. Returns a function that removes it."""
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def _on_change(self, event: Event[EventStateChangedData]) -> None:
        self._sample()
        self._notify()

    @callback
    def _on_tick(self, now: Any) -> None:
        self._sample()
        self._notify()

    @property
    def allocated_w(self) -> float:
        """Estimated draw of the rooms currently running on solar."""
        return sum(r.est_load_w for r in self.rooms.values() if r.running_on_solar)

    @property
    def budget_w(self) -> float | None:
        """Total solar the air conditioners may use: export less reserve plus what they already draw."""
        average = self.average_export_w
        if average is None:
            return None
        return average - self.reserve_w + self.allocated_w

    @property
    def average_export_w(self) -> float | None:
        """Smoothed export in watts, or None if there is no recent reading."""
        return self._average.average(dt_util.utcnow())

    def allowed(self, room_id: str) -> bool:
        """Return True if the room may run on excess solar right now."""
        if not self.export_sensor:
            return False
        if self.average_export_w is None:
            # No export reading yet, e.g. just after a restart. Keep rooms that
            # were already running on solar going instead of stopping them.
            room = self.rooms.get(room_id)
            return bool(room and room.running_on_solar)
        rooms = [
            SolarRoom(r.room_id, r.priority, r.est_load_w, r.running_on_solar)
            for r in self.rooms.values()
            if r.has_solar and r.enabled
        ]
        return solar_allowed(room_id, rooms, self.average_export_w, self.reserve_w)


class RoomRunner:
    """Evaluates one room and drives its climate entity."""

    def __init__(self, hass: HomeAssistant, hub: SolarHub, subentry: ConfigSubentry) -> None:
        data = subentry.data
        self.hass = hass
        self.hub = hub
        self.room_id = subentry.subentry_id
        self.name = subentry.title
        self.climate: str = data[CONF_CLIMATE]
        self.sensor: str | None = data.get(CONF_TEMP_SENSOR) or None
        self.sleep_timer: str | None = data.get(CONF_SLEEP_TIMER) or None
        self.settings = build_settings(data)
        self.max_age = timedelta(
            minutes=_number(data.get(CONF_MAX_SENSOR_AGE), DEFAULT_MAX_SENSOR_AGE)
        )
        self.has_solar = any(p.name == PROFILE_SOLAR for p in self.settings.profiles)
        self.est_load_w = _number(data.get(f"{PROFILE_SOLAR}_{CONF_EST_LOAD_W}"), 1500)
        self.priority = int(_number(data.get(f"{PROFILE_SOLAR}_{CONF_PRIORITY}"), 1))

        self.target = _number(data.get(CONF_DEFAULT_TARGET), DEFAULT_TARGET)
        self.enabled = True
        self.status = STATUS_IDLE
        self.reason: str | None = None
        self.profile: str | None = None
        self.last_error: str | None = None
        self.last_change = None
        self.running_on_solar = False
        # True once the unit has run under one of our profiles. Only owned
        # units are stopped when no profile is open, so manual use is left alone.
        self.owned = False
        self._load(hub.saved.get(self.room_id))

        self._restored: set[str] = set()
        self._started = False
        # Until the unit has reported in since startup, keep showing the
        # status restored from before the restart instead of "unavailable".
        self._unit_seen = False
        self._status_restored = False
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []

    # -- entity plumbing -------------------------------------------------

    @callback
    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register an entity callback. Returns a function that removes it."""
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    def _load(self, saved: Mapping[str, Any] | None) -> None:
        """Restore what the room knew before the last restart."""
        if not saved:
            return
        self.owned = bool(saved.get("owned", False))
        self.running_on_solar = bool(saved.get("running_on_solar", False))
        last_change = saved.get("last_change")
        self.last_change = dt_util.parse_datetime(last_change) if last_change else None

    def persisted(self) -> dict[str, Any]:
        """Return the state that must survive a restart."""
        return {
            "owned": self.owned,
            "running_on_solar": self.running_on_solar,
            "last_change": self.last_change.isoformat() if self.last_change else None,
        }

    @callback
    def restore_status(self, status: str, reason: str | None, profile: str | None) -> None:
        """Show the last status until the first real evaluation."""
        if self._started or status == STATUS_DISABLED:
            return
        self.status = status
        self.reason = reason
        self.profile = profile
        self._status_restored = True

    @callback
    def restore_target(self, value: float | None) -> None:
        """Set the target restored from the last run."""
        if value is not None:
            self.target = value
        self._mark_restored("number")

    @callback
    def restore_enabled(self, value: bool) -> None:
        """Set the enabled flag restored from the last run."""
        self.enabled = value
        self._mark_restored("switch")

    @callback
    def _mark_restored(self, kind: str) -> None:
        self._restored.add(kind)
        if self._started and self._restored == {"number", "switch"}:
            self.hass.async_create_task(self._async_evaluate())

    async def async_set_target(self, value: float) -> None:
        """Change the target temperature."""
        self.target = value
        self._notify()
        await self._async_evaluate()

    async def async_set_enabled(self, value: bool) -> None:
        """Turn control on or off for this room."""
        self.enabled = value
        self._notify()
        await self._async_evaluate()

    # -- lifecycle -------------------------------------------------------

    async def async_start(self) -> None:
        """Start listening and run a first evaluation."""
        entity_ids = [e for e in (self.climate, self.sensor, self.sleep_timer) if e]
        self._unsubs.append(
            async_track_state_change_event(self.hass, entity_ids, self._on_state)
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._async_evaluate, timedelta(seconds=EVALUATE_INTERVAL_SECONDS)
            )
        )
        self._started = True
        await self._async_evaluate()

    @callback
    def async_stop(self) -> None:
        """Stop listening."""
        self._started = False
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def _on_state(self, event: Event[EventStateChangedData]) -> None:
        self.hass.async_create_task(self._async_evaluate())

    def band_attributes(self) -> dict[str, Any]:
        """Describe the band the room is governed by, for dashboards."""
        now = dt_util.now().time()
        by_name = {p.name: p for p in self.settings.profiles}
        shown = by_name.get(self.profile) if self.profile else None
        next_start = None
        if shown is None:
            upcoming = next_profile(self.settings, now)
            if upcoming:
                shown, start = upcoming
                next_start = f"{start:%H:%M}"
        return {
            "summary_profile": shown.name if shown else None,
            "summary": band_summary(self.settings, shown, self.target) if shown else None,
            "window": profile_window(shown) if shown else None,
            "next_start": next_start,
            "solar_allowed": bool(self.has_solar and self.hub.allowed(self.room_id)),
            "bands": {
                p.name: {
                    **band(p, self.target),
                    "window": profile_window(p),
                    "summary": band_summary(self.settings, p, self.target),
                }
                for p in self.settings.profiles
            },
        }

    # -- reading the world -----------------------------------------------

    def _temperature(self) -> float | None:
        if self.sensor:
            state = self.hass.states.get(self.sensor)
            if state is None or state.state in UNAVAILABLE:
                return None
            try:
                value = float(state.state)
            except ValueError:
                return None
            if self.max_age:
                reported = getattr(state, "last_reported", None) or state.last_updated
                newest = max(reported, state.last_updated)
                if dt_util.utcnow() - newest > self.max_age:
                    return None
            return value
        climate = self.hass.states.get(self.climate)
        if climate is None:
            return None
        try:
            return float(climate.attributes.get("current_temperature"))
        except (TypeError, ValueError):
            return None

    def _effective_settings(self, climate: State | None) -> RoomSettings:
        """Narrow the configured limits to what the unit actually accepts."""
        if climate is None:
            return self.settings
        attrs = climate.attributes
        low = max(self.settings.min_set, _number(attrs.get("min_temp"), self.settings.min_set))
        high = min(self.settings.max_set, _number(attrs.get("max_temp"), self.settings.max_set))
        if low > high:
            low, high = self.settings.min_set, self.settings.max_set
        step = _number(attrs.get("target_temp_step"), 1.0) or 1.0
        fan = self.settings.fan_mode
        if fan:
            modes = attrs.get("fan_modes") or []
            fan = next((m for m in modes if str(m).lower() == fan.lower()), None)
        return dataclasses.replace(
            self.settings, min_set=low, max_set=high, step=step, fan_mode=fan
        )

    # -- evaluation ------------------------------------------------------

    async def _async_evaluate(self, *_: Any) -> None:
        if not self._started or self._restored != {"number", "switch"}:
            return
        async with self._lock:
            before = self.persisted()
            await self._evaluate()
            if self.persisted() != before:
                self.hub.schedule_save()

    async def _evaluate(self) -> None:
        if not self.enabled:
            self.status = STATUS_DISABLED
            self.reason = "disabled"
            self.profile = None
            self.running_on_solar = False
            self._notify()
            return

        climate = self.hass.states.get(self.climate)
        unit_mode = climate.state if climate else "unavailable"
        now = dt_util.now()
        sleeping = bool(
            self.sleep_timer and self.hass.states.is_state(self.sleep_timer, "active")
        )
        inputs = Inputs(
            now=now,
            current=self._temperature(),
            target=self.target,
            unit_mode=unit_mode,
            solar_ok=self.has_solar and self.hub.allowed(self.room_id),
            sleep_active=sleeping,
            last_change=self.last_change,
            owned=self.owned,
        )
        decision = decide(self._effective_settings(climate), inputs)
        await self._apply(decision, now)

        if unit_mode in UNAVAILABLE:
            # The unit has not loaded yet or is offline. Keep what we knew
            # about it rather than forgetting we own it.
            if not self._unit_seen and self._status_restored:
                self._notify()
                return
        elif decision.kind is ActionKind.START:
            self.owned = True
            self.running_on_solar = decision.profile == PROFILE_SOLAR
        elif decision.kind is ActionKind.STOP:
            self.owned = False
            self.running_on_solar = False
        else:
            if unit_mode not in RUNNING_MODES:
                self.owned = False
            elif decision.profile is not None:
                self.owned = True
            self.running_on_solar = (
                decision.profile == PROFILE_SOLAR and unit_mode in RUNNING_MODES
            )
        if unit_mode not in UNAVAILABLE:
            self._unit_seen = True

        self.reason = decision.reason
        self.profile = decision.profile
        self.status = self._status_for(decision, unit_mode)
        self._notify()

    @staticmethod
    def _status_for(decision: Decision, unit_mode: str) -> str:
        if decision.reason == R_SLEEP:
            return STATUS_SLEEP
        if decision.kind is ActionKind.START:
            return STATUS_HEATING if decision.mode is HvacMode.HEAT else STATUS_COOLING
        if decision.kind is ActionKind.STOP:
            return STATUS_IDLE
        if unit_mode == HvacMode.HEAT.value:
            return STATUS_HEATING
        if unit_mode == HvacMode.COOL.value:
            return STATUS_COOLING
        if decision.reason == R_MIN_OFF:
            return STATUS_WAITING
        return STATUS_IDLE

    async def _apply(self, decision: Decision, now: Any) -> None:
        if decision.kind is ActionKind.STOP:
            _LOGGER.debug("%s: stopping (%s)", self.name, decision.reason)
            if await self._call("turn_off", {}):
                self.last_change = now
        elif decision.kind is ActionKind.START and decision.mode is not None:
            _LOGGER.debug(
                "%s: starting %s at %s (%s)",
                self.name,
                decision.mode,
                decision.setpoint,
                decision.profile,
            )
            if await self._call("set_hvac_mode", {"hvac_mode": decision.mode.value}):
                self.last_change = now
                if decision.setpoint is not None:
                    await self._call("set_temperature", {"temperature": decision.setpoint})
                if decision.fan_mode:
                    await self._call("set_fan_mode", {"fan_mode": decision.fan_mode})

    async def _call(self, service: str, data: dict[str, Any]) -> bool:
        try:
            await self.hass.services.async_call(
                "climate",
                service,
                {"entity_id": self.climate, **data},
                blocking=True,
            )
        except HomeAssistantError as err:
            self.last_error = f"{service}: {err}"
            _LOGGER.warning("%s: climate.%s failed: %s", self.name, service, err)
            return False
        return True
