# Climate Governor

Set-and-forget thermostat bands for split-system air conditioners in Home Assistant.

Pick a target temperature for each room. The governor leaves the unit alone while the room stays inside a band around that target, switches it on when the room drifts outside, and switches it off again once the target is reached. Each room can run an overnight profile, a solar profile, or both, with its own settings.

## Install

1. In HACS, add this repository as a custom repository (category: Integration).
2. Install **Climate Governor** and restart Home Assistant.
3. Add the **Climate Governor** integration from Settings > Devices & services.

Requires Home Assistant 2025.3 or newer.

## Setup

**Hub.** Optionally choose a grid export power sensor (positive while exporting). Without one, solar profiles never run. The reserve is the amount of export to leave unused, and the averaging window smooths cloud flicker.

**Rooms.** Use *Add room* on the integration. Each room has:

- A climate entity, and optionally a temperature sensor (otherwise the unit's own reading is used) and a sleep timer that pauses control while active.
- Allowed modes, fan mode, setpoint limits, minimum run and off times, and an optional sensor age limit.
- An overnight profile and a solar profile.

Setpoints are rounded to the unit's step and clamped to both your limits and the limits the climate entity reports.

## Profiles

A profile is active when its time window is open (windows may cross midnight). With a target of `T`:

| Setting | Meaning |
| --- | --- |
| Start margin | Start heating at `T - margin` or below, cooling at `T + margin` or above |
| Stop margin | Stop heating at `T + margin`, cooling at `T - margin` |
| Overdrive | Command the unit to `T + overdrive` (heat) or `T - overdrive` (cool) |
| Target offset | Shift `T` while this profile is active (solar profile only) |

Profiles are checked in order, overnight first, and the first open one applies. When no profile is open, a unit the governor could be controlling is switched off. Units in other modes (dry, fan only) are left alone.

## Solar

A solar profile only runs while there is spare export. Each room declares an estimated power draw and a priority. The governor averages the export sensor, subtracts the reserve, and hands the budget to rooms in priority order (lowest number first). Rooms already running on solar count against the budget, and a room that no longer fits stops after its minimum run time.

## Entities

Each room gets a device with:

- `switch` Enabled: turn governing on or off for the room.
- `number` Target: the target temperature.
- `sensor` Status: `disabled`, `sleep`, `idle`, `heating`, `cooling` or `waiting`, with `reason`, `profile`, `last_error` and `export_w` attributes.

## Development

```
pip install -r requirements_test.txt
pytest
```

The decision logic lives in `controller.py` and `solar.py` with no Home Assistant imports, so it is tested directly. `runtime.py` connects it to Home Assistant.
