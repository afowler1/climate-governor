"""Per-room target temperature."""

from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ClimateGovernorConfigEntry
from .entity import RoomEntity
from .runtime import RoomRunner


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClimateGovernorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a target number for every room."""
    for subentry_id, runner in entry.runtime_data.rooms.items():
        async_add_entities([RoomTargetNumber(runner)], config_subentry_id=subentry_id)


class RoomTargetNumber(RoomEntity, RestoreNumber):
    """The temperature a room is held around."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 10.0
    _attr_native_max_value = 35.0
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX

    def __init__(self, runner: RoomRunner) -> None:
        super().__init__(runner, "target")

    async def async_added_to_hass(self) -> None:
        """Restore the last known target."""
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        self._runner.restore_target(last.native_value if last else None)

    @property
    def native_value(self) -> float:
        """Return the current target."""
        return self._runner.target

    async def async_set_native_value(self, value: float) -> None:
        """Change the target."""
        await self._runner.async_set_target(value)
