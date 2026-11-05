"""Per-room status sensor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ClimateGovernorConfigEntry
from .const import STATUSES
from .entity import RoomEntity
from .runtime import RoomRunner


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClimateGovernorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a status sensor for every room."""
    for subentry_id, runner in entry.runtime_data.rooms.items():
        async_add_entities([RoomStatusSensor(runner)], config_subentry_id=subentry_id)


class RoomStatusSensor(RoomEntity, SensorEntity):
    """What the governor is doing in a room, and why."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUSES

    def __init__(self, runner: RoomRunner) -> None:
        super().__init__(runner, "status")

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
        }
