"""Shared base entity."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .runtime import RoomRunner


class RoomEntity(RestoreEntity, Entity):
    """Base class for the entities that belong to a room."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runner: RoomRunner, key: str) -> None:
        self._runner = runner
        self._attr_unique_id = f"{runner.room_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, runner.room_id)},
            name=runner.name,
            manufacturer="Climate Governor",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to runner updates."""
        await super().async_added_to_hass()
        self.async_on_remove(self._runner.add_listener(self.async_write_ha_state))
