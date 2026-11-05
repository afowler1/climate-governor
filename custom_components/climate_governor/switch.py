"""Per-room enable switch."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF
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
    """Add a switch for every room."""
    for subentry_id, runner in entry.runtime_data.rooms.items():
        async_add_entities([RoomEnabledSwitch(runner)], config_subentry_id=subentry_id)


class RoomEnabledSwitch(RoomEntity, SwitchEntity):
    """Turns governing on or off for a room."""

    def __init__(self, runner: RoomRunner) -> None:
        super().__init__(runner, "enabled")

    async def async_added_to_hass(self) -> None:
        """Restore the last known state."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        self._runner.restore_enabled(last is None or last.state != STATE_OFF)

    @property
    def is_on(self) -> bool:
        """Return True if the room is being governed."""
        return self._runner.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the room."""
        await self._runner.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the room."""
        await self._runner.async_set_enabled(False)
