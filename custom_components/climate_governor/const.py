"""Constants for Climate Governor."""

from __future__ import annotations

DOMAIN = "climate_governor"
PLATFORMS = ["number", "sensor", "switch"]

SUBENTRY_ROOM = "room"

# Hub (config entry) options
CONF_EXPORT_SENSOR = "export_sensor"
CONF_RESERVE_W = "reserve_w"
CONF_SMOOTHING_MINUTES = "smoothing_minutes"

DEFAULT_RESERVE_W = 200
DEFAULT_SMOOTHING_MINUTES = 5

# Room (subentry) basics
CONF_NAME = "name"
CONF_CLIMATE = "climate_entity"
CONF_TEMP_SENSOR = "temperature_sensor"
CONF_SLEEP_TIMER = "sleep_timer"
CONF_DEFAULT_TARGET = "default_target"
CONF_ALLOW_HEAT = "allow_heat"
CONF_ALLOW_COOL = "allow_cool"
CONF_FAN_MODE = "fan_mode"
CONF_MIN_SET = "min_set"
CONF_MAX_SET = "max_set"
CONF_MIN_ON = "min_on_minutes"
CONF_MIN_OFF = "min_off_minutes"
CONF_MAX_SENSOR_AGE = "max_sensor_age_minutes"

DEFAULT_TARGET = 26.0
DEFAULT_MIN_ON = 5
DEFAULT_MIN_OFF = 5
DEFAULT_MAX_SENSOR_AGE = 180

# Profile keys are prefixed with the profile name
PROFILE_OVERNIGHT = "overnight"
PROFILE_SOLAR = "solar"

CONF_ENABLED = "enabled"
CONF_WINDOW_START = "window_start"
CONF_WINDOW_END = "window_end"
CONF_START_MARGIN = "start_margin"
CONF_STOP_MARGIN = "stop_margin"
CONF_OVERDRIVE = "overdrive"
CONF_TARGET_OFFSET = "target_offset"
CONF_EST_LOAD_W = "est_load_w"
CONF_PRIORITY = "priority"

# Status sensor states
STATUS_DISABLED = "disabled"
STATUS_SLEEP = "sleep"
STATUS_IDLE = "idle"
STATUS_HEATING = "heating"
STATUS_COOLING = "cooling"
STATUS_WAITING = "waiting"
STATUSES = [
    STATUS_DISABLED,
    STATUS_SLEEP,
    STATUS_IDLE,
    STATUS_HEATING,
    STATUS_COOLING,
    STATUS_WAITING,
]

EVALUATE_INTERVAL_SECONDS = 60
