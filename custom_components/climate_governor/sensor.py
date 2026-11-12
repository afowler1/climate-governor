"""Per-room status sensor."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ClimateGovernorConfigEntry
from .const import DOMAIN, STATUSES
from .entity import RoomEntity
from .runtime import RoomRunner, SolarHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClimateGovernorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a status sensor for every room, and the solar sensors for the hub."""
    for subentry_id, runner in entry.runtime_data.rooms.items():
        async_add_entities([RoomStatusSensor(runner)], config_subentry_id=subentry_id)
    hub = entry.runtime_data.hub
    async_add_entities(
        [
            HubSensor(hub, "solar_export", lambda h: h.average_export_w),
            HubSensor(hub, "solar_budget", lambda h: h.budget_w),
            HubSensor(hub, "solar_allocated", lambda h: h.allocated_w),
        ]
    )


class HubSensor(SensorEntity):
    """A solar figure shared by all rooms."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, hub: SolarHub, key: str, getter: Callable[[SolarHub], float | None]) -> None:
        self._hub = hub
        self._getter = getter
        self._attr_unique_id = f"{hub.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.entry_id)},
            name="Climate Governor",
            manufacturer="Climate Governor",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to hub updates."""
        self.async_on_remove(self._hub.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> float | None:
        """Return the current figure."""
        return self._getter(self._hub)


class RoomStatusSensor(RoomEntity, SensorEntity):
    """What the governor is doing in a room, and why."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUSES

    def __init__(self, runner: RoomRunner) -> None:
        super().__init__(runner, "status")

    async def async_added_to_hass(self) -> None:
        """Show the last status until the room is evaluated again."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in STATUSES:
            self._runner.restore_status(
                last.state, last.attributes.get("reason"), last.attributes.get("profile")
            )

    @property
    def native_value(self) -> str:
        """Return the current status."""
        return self._runner.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return why the governor last did what it did."""
        runner = self._runner
        return {
            "reason": runner.reason,
            "profile": runner.profile,
            "target": runner.target,
            "last_error": runner.last_error,
            "export_w": runner.hub.average_export_w,
            **runner.band_attributes(),
        }
