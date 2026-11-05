"""Config flow for Climate Governor."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TimeSelector,
)

from .const import (
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
    CONF_NAME,
    CONF_OVERDRIVE,
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
    DOMAIN,
    PROFILE_OVERNIGHT,
    PROFILE_SOLAR,
    SUBENTRY_ROOM,
)


def _box(low: float, high: float, step: float, unit: str | None = None) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=low,
            max=high,
            step=step,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


def _hub_schema(values: dict[str, Any]) -> vol.Schema:
    export = values.get(CONF_EXPORT_SENSOR)
    return vol.Schema(
        {
            vol.Optional(
                CONF_EXPORT_SENSOR,
                description={"suggested_value": export} if export else None,
            ): EntitySelector(EntitySelectorConfig(domain="sensor", device_class="power")),
            vol.Required(
                CONF_RESERVE_W, default=values.get(CONF_RESERVE_W, DEFAULT_RESERVE_W)
            ): _box(0, 5000, 50, "W"),
            vol.Required(
                CONF_SMOOTHING_MINUTES,
                default=values.get(CONF_SMOOTHING_MINUTES, DEFAULT_SMOOTHING_MINUTES),
            ): _box(1, 30, 1, "min"),
        }
    )


class ClimateGovernorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the single Climate Governor hub."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Rooms are added as subentries."""
        return {SUBENTRY_ROOM: RoomSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the hub."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="Climate Governor", data=user_input)
        return self.async_show_form(step_id="user", data_schema=_hub_schema({}))

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the solar settings."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            self.hass.config_entries.async_update_entry(entry, data=user_input)
            return self.async_abort(reason="reconfigure_successful")
        return self.async_show_form(
            step_id="reconfigure", data_schema=_hub_schema(dict(entry.data))
        )


class RoomSubentryFlow(ConfigSubentryFlow):
    """Add or change a room."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    # -- helpers ---------------------------------------------------------

    def _key(self, marker: type, key: str, default: Any = None) -> Any:
        """Build a schema key pre-filled from earlier input or a default."""
        value = self._data.get(key, default)
        if value is None or value == "":
            return marker(key)
        return marker(key, description={"suggested_value": value})

    def _profile_schema(self, name: str, defaults: dict[str, Any], solar: bool) -> vol.Schema:
        def k(field: str) -> str:
            return f"{name}_{field}"

        fields: dict[Any, Any] = {
            self._key(vol.Required, k(CONF_ENABLED), defaults[CONF_ENABLED]): BooleanSelector(),
            self._key(vol.Required, k(CONF_WINDOW_START), defaults[CONF_WINDOW_START]): TimeSelector(),
            self._key(vol.Required, k(CONF_WINDOW_END), defaults[CONF_WINDOW_END]): TimeSelector(),
            self._key(vol.Required, k(CONF_START_MARGIN), defaults[CONF_START_MARGIN]): _box(0, 15, 0.5, "°"),
            self._key(vol.Required, k(CONF_STOP_MARGIN), defaults[CONF_STOP_MARGIN]): _box(-5, 15, 0.5, "°"),
            self._key(vol.Required, k(CONF_OVERDRIVE), defaults[CONF_OVERDRIVE]): _box(0, 10, 0.5, "°"),
        }
        if solar:
            fields[self._key(vol.Required, k(CONF_TARGET_OFFSET), defaults[CONF_TARGET_OFFSET])] = _box(-10, 10, 0.5, "°")
            fields[self._key(vol.Required, k(CONF_EST_LOAD_W), defaults[CONF_EST_LOAD_W])] = _box(100, 8000, 50, "W")
            fields[self._key(vol.Required, k(CONF_PRIORITY), defaults[CONF_PRIORITY])] = _box(1, 20, 1)
        return vol.Schema(fields)

    def _basics_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                self._key(vol.Required, CONF_NAME): TextSelector(),
                self._key(vol.Required, CONF_CLIMATE): EntitySelector(
                    EntitySelectorConfig(domain="climate")
                ),
                self._key(vol.Optional, CONF_TEMP_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                self._key(vol.Optional, CONF_SLEEP_TIMER): EntitySelector(
                    EntitySelectorConfig(domain="timer")
                ),
                self._key(vol.Required, CONF_DEFAULT_TARGET, DEFAULT_TARGET): _box(10, 35, 0.5, "°C"),
                self._key(vol.Required, CONF_ALLOW_HEAT, True): BooleanSelector(),
                self._key(vol.Required, CONF_ALLOW_COOL, True): BooleanSelector(),
                self._key(vol.Optional, CONF_FAN_MODE): TextSelector(),
                self._key(vol.Optional, CONF_MIN_SET): _box(5, 35, 1, "°C"),
                self._key(vol.Optional, CONF_MAX_SET): _box(5, 35, 1, "°C"),
                self._key(vol.Required, CONF_MIN_ON, DEFAULT_MIN_ON): _box(0, 60, 1, "min"),
                self._key(vol.Required, CONF_MIN_OFF, DEFAULT_MIN_OFF): _box(0, 60, 1, "min"),
                self._key(vol.Required, CONF_MAX_SENSOR_AGE, DEFAULT_MAX_SENSOR_AGE): _box(0, 1440, 5, "min"),
            }
        )

    # -- steps -----------------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Add a room: basics first."""
        return await self._basics("user", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change a room: start from what is stored."""
        if user_input is None and not self._data:
            self._data = dict(self._get_reconfigure_subentry().data)
        return await self._basics("reconfigure", user_input)

    async def _basics(self, step_id: str, user_input: dict[str, Any] | None) -> SubentryFlowResult:
        if user_input is not None:
            # A cleared optional field is simply absent from the submission
            for key in (CONF_TEMP_SENSOR, CONF_SLEEP_TIMER, CONF_FAN_MODE, CONF_MIN_SET, CONF_MAX_SET):
                if key not in user_input:
                    self._data.pop(key, None)
            self._data.update(user_input)
            return await self.async_step_overnight()
        return self.async_show_form(step_id=step_id, data_schema=self._basics_schema())

    async def async_step_overnight(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Overnight profile."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_solar()
        defaults = {
            CONF_ENABLED: True,
            CONF_WINDOW_START: "21:00:00",
            CONF_WINDOW_END: "06:00:00",
            CONF_START_MARGIN: 5,
            CONF_STOP_MARGIN: 0,
            CONF_OVERDRIVE: 2,
        }
        return self.async_show_form(
            step_id="overnight",
            data_schema=self._profile_schema(PROFILE_OVERNIGHT, defaults, solar=False),
        )

    async def async_step_solar(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Solar profile."""
        if user_input is not None:
            self._data.update(user_input)
            return self._finish()
        defaults = {
            CONF_ENABLED: False,
            CONF_WINDOW_START: "09:00:00",
            CONF_WINDOW_END: "16:00:00",
            CONF_START_MARGIN: 1,
            CONF_STOP_MARGIN: 0.5,
            CONF_OVERDRIVE: 0,
            CONF_TARGET_OFFSET: -1,
            CONF_EST_LOAD_W: 1500,
            CONF_PRIORITY: 1,
        }
        return self.async_show_form(
            step_id="solar",
            data_schema=self._profile_schema(PROFILE_SOLAR, defaults, solar=True),
        )

    def _finish(self) -> SubentryFlowResult:
        title = self._data[CONF_NAME]
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                title=title,
                data=self._data,
            )
        return self.async_create_entry(title=title, data=self._data)
