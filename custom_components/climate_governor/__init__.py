"""Climate Governor: set-and-forget thermostat bands for split systems."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.start import async_at_started

from .const import PLATFORMS, SUBENTRY_ROOM
from .runtime import RoomRunner, SolarHub, async_remove_store


@dataclass
class GovernorData:
    """Objects shared by the platforms."""

    hub: SolarHub
    rooms: dict[str, RoomRunner]


type ClimateGovernorConfigEntry = ConfigEntry[GovernorData]


async def async_setup_entry(hass: HomeAssistant, entry: ClimateGovernorConfigEntry) -> bool:
    """Set up the hub and a runner per room."""
    hub = SolarHub(hass, entry)
    await hub.async_load()
    rooms = {
        subentry_id: RoomRunner(hass, hub, subentry)
        for subentry_id, subentry in entry.subentries.items()
        if subentry.subentry_type == SUBENTRY_ROOM
    }
    hub.rooms = rooms
    entry.runtime_data = GovernorData(hub=hub, rooms=rooms)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await hub.async_start()

    async def _async_start_rooms(_: HomeAssistant) -> None:
        for runner in rooms.values():
            await runner.async_start()

    # Wait until Home Assistant has fully started, so the climate entities
    # and sensors have loaded before any room acts on them.
    entry.async_on_unload(async_at_started(hass, _async_start_rooms))
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ClimateGovernorConfigEntry) -> bool:
    """Stop the runners and unload the platforms."""
    data = entry.runtime_data
    for runner in data.rooms.values():
        runner.async_stop()
    data.hub.async_stop()
    await data.hub.async_save()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ClimateGovernorConfigEntry) -> None:
    """Delete the saved room state."""
    await async_remove_store(hass, entry.entry_id)


async def _async_reload(hass: HomeAssistant, entry: ClimateGovernorConfigEntry) -> None:
    """Reload when settings or rooms change."""
    await hass.config_entries.async_reload(entry.entry_id)
